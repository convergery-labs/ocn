"""Orchestration for classification job submission and execution."""
import asyncio
import json
import logging
import os
import uuid
from functools import partial

import httpx
from datasketch import MinHash, MinHashLSH
from langdetect import DetectorFactory, detect
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from models.claims import insert_claim
from models.jobs import (
    JobRow,
    create_job,
    find_processing_job,
    insert_classification,
    update_job_status,
)

DetectorFactory.seed = 0  # deterministic language detection

logger = logging.getLogger(__name__)

_MINHASH_PERMS = 128
_MINHASH_THRESHOLD = 0.85
_EMBED_BATCH_SIZE = 50
_ARTICLE_VECTOR_SIZE = 3072
_CLAIM_VECTOR_SIZE = 1536


class RunNotFoundError(Exception):
    """Raised when the referenced news-retrieval run does not exist."""


class DuplicateJobError(Exception):
    """Raised when a processing job for run_id already exists."""


def _news_retrieval_url() -> str:
    """Return the news-retrieval base URL from env."""
    return os.environ.get(
        "NEWS_RETRIEVAL_URL", "http://news-retrieval:8000"
    )


async def validate_run_id(run_id: int) -> None:
    """Confirm run_id exists in news-retrieval; raise RunNotFoundError if not.

    Raises:
        RunNotFoundError: if the run does not exist or news-retrieval
            returns a non-200 response.
    """
    url = f"{_news_retrieval_url()}/runs/{run_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise RunNotFoundError(
            f"news-retrieval unreachable: {exc}"
        ) from exc
    if resp.status_code != 200:
        raise RunNotFoundError(
            f"run {run_id} not found in news-retrieval"
        )


async def submit_classify_job(
    run_id: str | None,
    articles: list[dict],
    callback_url: str | None,
) -> JobRow:
    """Validate, create a job record, and return it.

    For Mode A (run_id provided): verifies run existence and uniqueness.
    For Mode B (articles provided directly): generates a fresh run_id.

    Raises:
        RunNotFoundError: Mode A only — run_id not found.
        DuplicateJobError: Mode A only — processing job already exists.
    """
    if run_id is not None:
        await validate_run_id(int(run_id))
        existing = find_processing_job(run_id)
        if existing:
            raise DuplicateJobError(
                f"A processing job already exists for run_id={run_id}"
            )
        effective_run_id = run_id
    else:
        effective_run_id = str(uuid.uuid4())

    job = create_job(
        run_id=effective_run_id,
        status="processing",
        callback_url=callback_url,
        article_count=len(articles),
    )
    return job


async def run_classification_stub(
    job_id: int,
    articles: list[dict],
    callback_url: str | None,
) -> None:
    """Feature extraction background task for a classification job.

    For each article: MinHash dedup, language filter, body embedding,
    LLM claim extraction, claim embedding, and Postgres claim storage.
    Labels and scores are placeholders (CON-138 will update them).
    """
    try:
        await _run_feature_extraction(job_id, articles)
        update_job_status(job_id, "completed", set_completed_at=True)
    except Exception:
        logger.exception("Feature extraction failed for job %d", job_id)
        try:
            update_job_status(job_id, "failed", set_completed_at=True)
        except Exception:
            logger.exception(
                "Failed to mark job %d failed", job_id
            )
        if callback_url:
            _fire_callback(callback_url, job_id, "failed")
        return
    if callback_url:
        _fire_callback(callback_url, job_id, "completed")


async def _embed_and_store(
    *,
    job_id: int,
    classification_id: int,
    article_url: str,
    claims: list[str],
    oai: OpenAI,
    claim_embedding_model: str,
    qdrant: QdrantClient,
    loop: asyncio.AbstractEventLoop,
    trace: object,
) -> None:
    """Embed claims for one article and persist them to Qdrant and Postgres.

    Args:
        job_id: Classification job identifier for log messages.
        classification_id: DB row id for the article's classification.
        article_url: Source URL of the article.
        claims: List of factual claim strings to embed and store.
        oai: OpenAI-compatible client.
        claim_embedding_model: Model identifier for claim embeddings.
        qdrant: Qdrant client.
        loop: Running event loop used to offload blocking calls.
        trace: Langfuse trace object, or None if tracing is disabled.
    """
    if not claims:
        return
    article_qdrant_id = _url_to_point_id(article_url)
    claim_embeddings = await loop.run_in_executor(
        None,
        partial(_embed_texts, oai, claim_embedding_model, claims),
    )
    if trace:
        trace.span(
            name="claim-embedding",
            input={
                "claim_count": len(claims),
                "url": article_url,
            },
        )
    claim_points = [
        PointStruct(
            id=_url_to_point_id(claim_text),
            vector=claim_emb,
            payload={
                "article_qdrant_id": article_qdrant_id,
                "article_url": article_url,
                "claim_text": claim_text,
            },
        )
        for claim_text, claim_emb in zip(claims, claim_embeddings)
    ]
    qdrant.upsert(collection_name="claims", points=claim_points)
    for claim_text, claim_point in zip(claims, claim_points):
        insert_claim(
            classification_id=classification_id,
            claim_text=claim_text,
            claim_embedding_id=str(claim_point.id),
            embedding_model=claim_embedding_model,
        )
    logger.info(
        "Job %d: stored %d claims for %s",
        job_id, len(claims), article_url,
    )


async def _run_feature_extraction(
    job_id: int,
    articles: list[dict],
) -> None:
    """Execute dedup → lang-filter → embed → claim extract → store.

    Claim extraction for all articles is performed concurrently via
    asyncio.gather, then claim embeddings are gathered concurrently as
    well, reducing total LLM round-trips from O(N×2) to O(2 batched
    async rounds).
    """
    if not articles:
        return

    lf = _langfuse_client()
    trace = (
        lf.trace(name="feature-extraction", session_id=str(job_id))
        if lf else None
    )

    oai = _openai_client()
    embedding_model = _embedding_model()
    claim_embedding_model = _claim_embedding_model()
    llm_model = _llm_model()
    qdrant = _qdrant_client()

    _ensure_qdrant_collection(qdrant, "articles", _ARTICLE_VECTOR_SIZE)
    _ensure_qdrant_collection(qdrant, "claims", _CLAIM_VECTOR_SIZE)

    # Step 1 — MinHash LSH deduplication (within-batch)
    keep_indices = _dedup_indices(articles)
    deduped = [articles[i] for i in keep_indices]
    skipped = len(articles) - len(deduped)
    if skipped:
        logger.info(
            "Job %d: MinHash dedup skipped %d near-duplicate articles",
            job_id, skipped,
        )

    # Step 2 — Language filter
    english = []
    for article in deduped:
        lang = _detect_language(article.get("body", ""))
        if trace:
            trace.span(
                name="language-filter",
                input={"url": article.get("url", "")},
                output={"lang": lang},
            )
        if lang != "en":
            logger.info(
                "Job %d: skipping non-English article %s (lang=%s)",
                job_id, article.get("url", ""), lang,
            )
            continue
        english.append(article)

    if not english:
        logger.info("Job %d: no English articles to process", job_id)
        return

    # Step 3 — Embed article bodies in batches
    bodies = [a.get("body", "") for a in english]
    total_chars = sum(len(b) for b in bodies)
    if trace:
        trace.span(
            name="article-embedding",
            input={"char_count": total_chars, "article_count": len(english)},
        )

    loop = asyncio.get_running_loop()
    all_embeddings: list[list[float]] = []
    for i in range(0, len(english), _EMBED_BATCH_SIZE):
        batch_bodies = bodies[i: i + _EMBED_BATCH_SIZE]
        batch_embeddings = _embed_texts(oai, embedding_model, batch_bodies)
        all_embeddings.extend(batch_embeddings)

    # Step 4 — Upsert article vectors to Qdrant and insert DB rows
    article_points = [
        PointStruct(
            id=_url_to_point_id(a["url"]),
            vector=emb,
            payload={
                "url": a.get("url", ""),
                "domain": a.get("source", ""),
                "published_date": a.get("published", ""),
                "label": None,
            },
        )
        for a, emb in zip(english, all_embeddings)
    ]
    qdrant.upsert(collection_name="articles", points=article_points)
    logger.info(
        "Job %d: upserted %d articles to Qdrant", job_id, len(article_points)
    )

    # Step 5 — Insert classification rows and collect per-article metadata
    classification_ids: list[int] = []
    article_urls: list[str] = []
    article_bodies: list[str] = []
    for article, embedding in zip(english, all_embeddings):
        article_url = article.get("url", "")
        classification_id = insert_classification(
            job_id=job_id,
            article_url=article_url,
            article_embedding=embedding,
            model_embedding=embedding_model,
            model_llm=llm_model,
        )
        classification_ids.append(classification_id)
        article_urls.append(article_url)
        article_bodies.append(article.get("body", ""))

    # Step 6 — Extract claims for all articles concurrently
    all_claims: list[list[str]] = await asyncio.gather(
        *[
            loop.run_in_executor(
                None,
                partial(_extract_claims, oai, llm_model, body),
            )
            for body in article_bodies
        ]
    )

    if trace:
        for article_url, body, claims in zip(
            article_urls, article_bodies, all_claims
        ):
            if claims:
                trace.span(
                    name="claim-extraction",
                    input={
                        "url": article_url,
                        "body_preview": body[:500],
                    },
                    output={"claims": claims},
                )

    # Step 7 — Embed claims for all articles concurrently, then store
    await asyncio.gather(
        *[
            _embed_and_store(
                job_id=job_id,
                classification_id=cid,
                article_url=url,
                claims=claims,
                oai=oai,
                claim_embedding_model=claim_embedding_model,
                qdrant=qdrant,
                loop=loop,
                trace=trace,
            )
            for cid, url, claims in zip(
                classification_ids, article_urls, all_claims
            )
        ]
    )

    if lf:
        lf.flush()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _qdrant_client() -> QdrantClient:
    """Return a configured Qdrant client."""
    host = os.environ.get("QDRANT_HOST", "qdrant")
    api_key = os.environ.get("QDRANT_API_KEY")
    if host.startswith("http"):
        return QdrantClient(url=host, api_key=api_key)
    return QdrantClient(
        host=host,
        port=int(os.environ.get("QDRANT_PORT", "6333")),
        api_key=api_key,
    )


def _openai_client() -> OpenAI:
    """Return an OpenAI client pointed at OpenRouter."""
    return OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )


def _embedding_model() -> str:
    """Return the configured article embedding model."""
    return os.environ.get(
        "EMBEDDING_MODEL", "openai/text-embedding-3-large"
    )


def _claim_embedding_model() -> str:
    """Return the configured claim embedding model."""
    return os.environ.get(
        "CLAIM_EMBEDDING_MODEL", "openai/text-embedding-3-small"
    )


def _llm_model() -> str:
    """Return the configured LLM model for claim extraction."""
    return os.environ.get("OPENROUTER_MODEL", "inclusionai/ling-2.6-flash:free")


def _langfuse_client():
    """Return a Langfuse client, or None if credentials are not configured."""
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return None
    try:
        from langfuse import Langfuse
        return Langfuse()
    except Exception:
        logger.debug("Langfuse init failed; tracing disabled", exc_info=True)
        return None


def _url_to_point_id(url: str) -> str:
    """Return a deterministic UUID5 point ID for a URL or claim text."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url))


def _ensure_qdrant_collection(
    client: QdrantClient,
    name: str,
    size: int,
) -> None:
    """Create Qdrant collection *name* if it does not already exist."""
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=size,
                distance=Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection: %s", name)


def _dedup_indices(articles: list[dict]) -> list[int]:
    """Return indices of articles that survive MinHash LSH deduplication.

    Articles with Jaccard similarity > _MINHASH_THRESHOLD against any
    already-kept article are dropped.
    """
    lsh = MinHashLSH(threshold=_MINHASH_THRESHOLD, num_perm=_MINHASH_PERMS)
    keep: list[int] = []
    for idx, article in enumerate(articles):
        body = article.get("body", "")
        tokens = body.lower().split()
        mh = MinHash(num_perm=_MINHASH_PERMS)
        for token in tokens:
            mh.update(token.encode("utf-8"))
        key = str(idx)
        if not lsh.query(mh):
            lsh.insert(key, mh)
            keep.append(idx)
        else:
            logger.info(
                "Dedup: skipping near-duplicate article index %d (%s)",
                idx,
                article.get("url", ""),
            )
    return keep


def _detect_language(text: str) -> str:
    """Return ISO 639-1 language code for *text*, or 'unknown' on failure."""
    try:
        return detect(text)
    except Exception:
        return "unknown"


def _embed_texts(
    client: OpenAI,
    model: str,
    texts: list[str],
) -> list[list[float]]:
    """Embed *texts* in one batch via OpenRouter. Truncates to 30K chars."""
    truncated = [t[:30_000] for t in texts]
    response = client.embeddings.create(model=model, input=truncated)
    return [item.embedding for item in response.data]


def _extract_claims(
    client: OpenAI,
    model: str,
    body: str,
) -> list[str]:
    """Extract 3-5 factual claims from *body* via LLM.

    Returns an empty list if the LLM returns malformed JSON or fails.
    """
    prompt = (
        "Extract 3 to 5 distinct, verifiable factual claims from the "
        "article below.\n"
        "Return ONLY a JSON array of strings, no other text.\n"
        'Example: ["Claim one.", "Claim two."]\n\n'
        f"Article:\n{body}"
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content or ""
        claims = json.loads(raw)
        if not isinstance(claims, list):
            raise ValueError("LLM did not return a JSON array")
        return [str(c) for c in claims if c]
    except Exception:
        logger.warning(
            "Claim extraction failed; falling back to no claims",
            exc_info=True,
        )
        return []


def _fire_callback(
    callback_url: str,
    job_id: int,
    status: str,
) -> None:
    """POST job completion status to callback_url; errors are swallowed."""
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                callback_url,
                json={"job_id": job_id, "status": status},
            )
    except Exception:
        logger.warning(
            "Callback to %s failed for job %d", callback_url, job_id
        )
