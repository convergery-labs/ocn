"""Orchestration for classification job submission and execution."""
import asyncio
import contextlib
import json
import logging
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from itertools import combinations

import httpx
import numpy as np
from datasketch import MinHash, MinHashLSH
from langdetect import DetectorFactory, detect
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from models.claims import insert_claim
from models.clusters import get_clusters_for_domain
from models.cooccurrences import (
    get_cooccurrence_counts,
    upsert_cooccurrences,
)
from models.jobs import (
    JobRow,
    create_job,
    find_processing_job,
    insert_classification,
    insert_deferred_promotion,
    update_classification_concepts,
    update_classification_plausibility,
    update_classification_scores,
    update_job_status,
)
from pipeline.ner import extract_concepts

DetectorFactory.seed = 0  # deterministic language detection

logger = logging.getLogger(__name__)

_MINHASH_PERMS = 128
_MINHASH_THRESHOLD = 0.85
_EMBED_BATCH_SIZE = 50
_ARTICLE_VECTOR_SIZE = 3072
_CLAIM_VECTOR_SIZE = 1536

# Scoring hyper-parameters — all overridable via environment variables
_MIN_CLUSTER_SIMILARITY = float(
    os.environ.get("MIN_CLUSTER_SIMILARITY", "0.3")
)
_COLD_START_CLAIM_SCORE = float(
    os.environ.get("COLD_START_CLAIM_SCORE", "0.5")
)
_W_TRAJECTORY = float(os.environ.get("W_TRAJECTORY", "0.40"))
_W_CLAIM_NOVELTY = float(os.environ.get("W_CLAIM_NOVELTY", "0.60"))
# Phase 4 weights — used when bridge score is available
_W_TRAJ_P4 = float(os.environ.get("W_TRAJECTORY_P4", "0.25"))
_W_BRIDGE = float(os.environ.get("W_BRIDGE", "0.30"))
_W_NOVELTY_P4 = float(os.environ.get("W_CLAIM_NOVELTY_P4", "0.45"))
_SIGNAL_THRESHOLD = float(os.environ.get("SIGNAL_THRESHOLD", "0.70"))
_WEAK_SIGNAL_THRESHOLD = float(
    os.environ.get("WEAK_SIGNAL_THRESHOLD", "0.40")
)
_CLAIM_NOVELTY_K = 10
_DEFERRAL_DAYS = 30

# Plausibility filter hyper-parameters
_PLAUSIBILITY_THRESHOLD = float(
    os.environ.get("PLAUSIBILITY_THRESHOLD", "0.40")
)
_PLAUSIBILITY_DOWNGRADE_THRESHOLD = float(
    os.environ.get("PLAUSIBILITY_DOWNGRADE_THRESHOLD", "0.30")
)
_PLAUSIBILITY_TOKEN_WARN_THRESHOLD = int(
    os.environ.get("PLAUSIBILITY_TOKEN_WARN_THRESHOLD", "4096")
)
_PLAUSIBILITY_BODY_CHARS = 8_000  # ~2,000 tokens


class RunNotFoundError(Exception):
    """Raised when the referenced news-retrieval run does not exist."""


class DuplicateJobError(Exception):
    """Raised when a processing job for run_id already exists."""


class DomainNotFoundError(Exception):
    """Raised when the domain slug is not registered in news-retrieval."""


def _news_retrieval_url() -> str:
    """Return the news-retrieval base URL from env."""
    return os.environ.get(
        "NEWS_RETRIEVAL_URL", "http://news-retrieval:8000"
    )


async def validate_domain(domain: str) -> None:
    """Confirm domain slug is registered in news-retrieval.

    Raises:
        DomainNotFoundError: if the slug is absent from GET /domains or
            news-retrieval is unreachable.
    """
    url = f"{_news_retrieval_url()}/domains"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise DomainNotFoundError(
            f"news-retrieval unreachable while validating domain: {exc}"
        ) from exc
    slugs = {d.get("slug") for d in resp.json()}
    if domain not in slugs:
        raise DomainNotFoundError(
            f"Domain '{domain}' is not registered in news-retrieval. "
            f"Classification cannot proceed: there is no corpus to compare "
            f"articles against."
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
    domain: str,
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
        domain=domain,
    )
    return job


async def run_agent_loop(
    job_id: int,
    articles: list[dict],
    callback_url: str | None,
    domain: str,
) -> None:
    """Agent loop: feature extraction → scoring → label assignment.

    Steps: preprocessing → topic cluster assignment → trajectory
    deviation → claim novelty → composite score → label. Each named
    sub-step is a standalone function.
    """
    status = "completed"
    try:
        qdrant = _qdrant_client()
        await _run_feature_extraction(job_id, articles, domain)
        await _run_scoring_phase(job_id, qdrant, articles, domain)
        update_job_status(job_id, "completed", set_completed_at=True)
    except Exception:
        logger.exception("Agent loop failed for job %d", job_id)
        status = "failed"
        try:
            update_job_status(job_id, "failed", set_completed_at=True)
        except Exception:
            logger.exception(
                "Failed to mark job %d failed", job_id
            )
    if callback_url:
        _fire_callback(callback_url, job_id, status)


async def _run_scoring_phase(
    job_id: int,
    qdrant: QdrantClient,
    articles: list[dict],
    domain: str,
) -> None:
    """Score every classification in job_id and write results to DB.

    Reads article embeddings and claim IDs from Postgres, then runs
    the named scoring steps for each article.
    """
    from db import get_db

    loop = asyncio.get_running_loop()
    oai = _openai_client()
    article_lookup = {a.get("url", ""): a for a in articles}
    lf = _langfuse_client()

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT c.id,
                   c.article_url,
                   c.source,
                   c.article_embedding,
                   c.concepts,
                   array_agg(
                       cl.claim_embedding_id::text
                   ) FILTER (WHERE cl.id IS NOT NULL) AS claim_ids
            FROM classifications c
            LEFT JOIN claims cl ON cl.classification_id = c.id
            WHERE c.job_id = :job_id
            GROUP BY c.id, c.article_url, c.source,
                     c.article_embedding, c.concepts
            """,
            {"job_id": job_id},
        ).fetchall()

    span_ctx = (
        lf.start_as_current_observation(
            name="scoring",
            input={"job_id": job_id, "article_count": len(rows)},
        )
        if lf else contextlib.nullcontext()
    )
    with span_ctx as span:
        for row in rows:
            row = dict(row)
            classification_id = row["id"]
            article_url = row["article_url"]
            source = row["source"] or ""
            embedding = row["article_embedding"] or []
            claim_ids = row["claim_ids"] or []
            article_qdrant_id = _url_to_point_id(article_url)

            clusters = get_clusters_for_domain(domain)
            cluster_id, traj_score, low_conf = _assign_cluster(
                embedding, clusters
            )
            if low_conf:
                logger.info(
                    "Job %d: low-confidence cluster assignment for %s",
                    job_id, article_url,
                )

            claim_novelty = await loop.run_in_executor(
                None,
                partial(
                    _compute_claim_novelty,
                    claim_ids,
                    article_qdrant_id,
                    qdrant,
                    domain,
                ),
            )

            concepts = row.get("concepts") or []
            pairs = list(combinations(sorted(concepts), 2))
            counts = get_cooccurrence_counts(pairs, domain)
            bridge = _compute_bridge_score(concepts, counts)
            if bridge is None:
                logger.info(
                    "Job %d: bridge_score_unavailable for %s",
                    job_id, article_url,
                )

            composite = _compute_composite(traj_score, claim_novelty, bridge)
            label = _assign_label(composite)

            plausibility_score = None
            plausibility_flags = None
            plausibility_reasoning = None
            flagged_for_review = False

            if composite > _PLAUSIBILITY_THRESHOLD:
                article = article_lookup.get(article_url, {})
                result = await loop.run_in_executor(
                    None,
                    partial(
                        _call_plausibility_llm,
                        oai,
                        _plausibility_model(),
                        article.get("title", ""),
                        article.get("body") or article.get("summary", ""),
                        composite,
                    ),
                )
                if result is not None:
                    plausibility_score = result["plausibility_score"]
                    plausibility_flags = result.get("flags", [])
                    plausibility_reasoning = result.get("reasoning", "")
                    label, flagged_for_review = _apply_plausibility_downgrade(
                        label, plausibility_score
                    )
                    if span:
                        span.start_observation(
                            name="plausibility",
                            input={
                                "url": article_url,
                                "composite": composite,
                            },
                            output={
                                "plausibility_score": plausibility_score,
                                "flags": plausibility_flags,
                                "total_tokens": result.get("total_tokens", 0),
                            },
                        ).end()
                    if flagged_for_review:
                        logger.info(
                            "Job %d: flagged for review — %s"
                            " (plausibility=%.3f)",
                            job_id, article_url, plausibility_score,
                        )

            # Only write corpus mutations for non-Signal articles.
            # Signal articles are deferred: co-occurrences and claim
            # vectors are withheld until promotion confirms the label.
            if label != "Signal":
                upsert_cooccurrences(concepts, domain)

            update_classification_scores(
                classification_id=classification_id,
                label=label,
                composite_score=composite,
                trajectory_score=traj_score,
                claim_novelty_score=claim_novelty,
                bridge_score=bridge,
                cluster_id=cluster_id,
            )
            update_classification_plausibility(
                classification_id=classification_id,
                plausibility_score=plausibility_score,
                plausibility_flags=plausibility_flags,
                plausibility_reasoning=plausibility_reasoning,
                flagged_for_review=flagged_for_review,
            )

            if label == "Signal":
                promote_at = datetime.now(tz=timezone.utc) + timedelta(
                    days=_DEFERRAL_DAYS
                )
                insert_deferred_promotion(
                    classification_id=classification_id,
                    promote_at=promote_at,
                )
                _defer_claims_in_qdrant(qdrant, claim_ids)

            bridge_str = f"{bridge:.3f}" if bridge is not None else "null"
            p_str = (
                f"{plausibility_score:.3f}"
                if plausibility_score is not None else "null"
            )
            logger.info(
                "Job %d: %s → label=%s composite=%.3f"
                " traj=%.3f bridge=%s novelty=%.3f plausibility=%s"
                " flagged=%s",
                job_id, article_url, label,
                composite, traj_score, bridge_str, claim_novelty,
                p_str, flagged_for_review,
            )

    if lf:
        lf.flush()


async def _embed_and_store(
    *,
    job_id: int,
    classification_id: int,
    article_url: str,
    claims: list[str],
    domain: str,
    oai: OpenAI,
    claim_embedding_model: str,
    qdrant: QdrantClient,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Embed claims for one article and persist them to Qdrant and Postgres.

    Args:
        job_id: Classification job identifier for log messages.
        classification_id: DB row id for the article's classification.
        article_url: Source URL of the article.
        claims: List of factual claim strings to embed and store.
        domain: Domain slug; stored in the Qdrant payload for scoped
            novelty searches.
        oai: OpenAI-compatible client.
        claim_embedding_model: Model identifier for claim embeddings.
        qdrant: Qdrant client.
        loop: Running event loop used to offload blocking calls.
    """
    if not claims:
        return
    article_qdrant_id = _url_to_point_id(article_url)
    claim_embeddings = await loop.run_in_executor(
        None,
        partial(_embed_texts, oai, claim_embedding_model, claims),
    )
    claim_points = [
        PointStruct(
            id=_url_to_point_id(claim_text),
            vector=claim_emb,
            payload={
                "article_qdrant_id": article_qdrant_id,
                "article_url": article_url,
                "claim_text": claim_text,
                "domain": domain,
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
    domain: str,
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
    span_ctx = (
        lf.start_as_current_observation(
            name="feature-extraction",
            input={"job_id": job_id, "article_count": len(articles)},
        )
        if lf else contextlib.nullcontext()
    )

    oai = _openai_client()
    embedding_model = _embedding_model()
    claim_embedding_model = _claim_embedding_model()
    llm_model = _llm_model()
    qdrant = _qdrant_client()

    _ensure_qdrant_collection(qdrant, "articles", _ARTICLE_VECTOR_SIZE)
    _ensure_qdrant_collection(qdrant, "claims", _CLAIM_VECTOR_SIZE)

    with span_ctx as span:
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
            lang = _detect_language(article.get("body") or article.get("summary", ""))
            if span:
                span.start_observation(
                    name="language-filter",
                    input={"url": article.get("url", "")},
                    output={"lang": lang},
                ).end()
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
        bodies = [a.get("body") or a.get("summary", "") for a in english]
        total_chars = sum(len(b) for b in bodies)
        if span:
            span.start_observation(
                name="article-embedding",
                input={
                    "char_count": total_chars,
                    "article_count": len(english),
                },
            ).end()

        loop = asyncio.get_running_loop()
        all_embeddings: list[list[float]] = []
        for i in range(0, len(english), _EMBED_BATCH_SIZE):
            batch_bodies = bodies[i: i + _EMBED_BATCH_SIZE]
            batch_embeddings = _embed_texts(
                oai, embedding_model, batch_bodies
            )
            all_embeddings.extend(batch_embeddings)

        # Step 4 — Upsert article vectors to Qdrant and insert DB rows
        article_points = [
            PointStruct(
                id=_url_to_point_id(a["url"]),
                vector=emb,
                payload={
                    "url": a.get("url", ""),
                    "domain": domain,
                    "published_date": a.get("published", ""),
                    "label": None,
                },
            )
            for a, emb in zip(english, all_embeddings)
        ]
        qdrant.upsert(collection_name="articles", points=article_points)
        logger.info(
            "Job %d: upserted %d articles to Qdrant",
            job_id, len(article_points),
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
                source=article.get("source"),
                title=article.get("title"),
                summary=article.get("summary"),
                body=article.get("body"),
                published=article.get("published"),
            )
            classification_ids.append(classification_id)
            article_urls.append(article_url)
            article_bodies.append(article.get("body") or article.get("summary", ""))

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

        if span:
            for article_url, body, claims in zip(
                article_urls, article_bodies, all_claims
            ):
                if claims:
                    span.start_observation(
                        name="claim-extraction",
                        input={
                            "url": article_url,
                            "body_preview": body[:500],
                        },
                        output={"claims": claims},
                    ).end()

        # Step 7 — Embed claims for all articles concurrently, then store
        await asyncio.gather(
            *[
                _embed_and_store(
                    job_id=job_id,
                    classification_id=cid,
                    article_url=url,
                    claims=claims,
                    domain=domain,
                    oai=oai,
                    claim_embedding_model=claim_embedding_model,
                    qdrant=qdrant,
                    loop=loop,
                )
                for cid, url, claims in zip(
                    classification_ids, article_urls, all_claims
                )
            ]
        )

        # Step 8 — NER concept extraction; results stored on classifications row
        article_titles = [a.get("title", "") for a in english]
        all_concepts: list[list[str]] = await asyncio.gather(
            *[
                loop.run_in_executor(
                    None,
                    extract_concepts,
                    f"{title} {body}",
                )
                for title, body in zip(article_titles, article_bodies)
            ]
        )
        for cid, article_url, concepts in zip(
            classification_ids, article_urls, all_concepts
        ):
            if not concepts:
                logger.warning(
                    "Job %d: no concepts matched for %s",
                    job_id, article_url,
                )
            update_classification_concepts(cid, concepts)

    if lf:
        lf.flush()


# ---------------------------------------------------------------------------
# Scoring helpers (each is a named, independently testable step)
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity between two vectors."""
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    norm = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr))
    if norm == 0.0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / norm)


def _assign_cluster(
    embedding: list[float],
    clusters: list[dict],
) -> tuple[int | None, float, bool]:
    """Assign article to the nearest topic cluster by centroid similarity.

    Returns (cluster_id, trajectory_score, low_confidence).
    trajectory_score = 1 - cosine_similarity, normalised to [0, 1].
    low_confidence is True when similarity < _MIN_CLUSTER_SIMILARITY,
    or when no valid centroid vectors are available (cold start).
    """
    valid = [
        c for c in clusters if c.get("centroid_vector") is not None
    ]
    if not valid:
        return None, _COLD_START_CLAIM_SCORE, True

    best_id: int | None = None
    best_sim = -1.0
    for cluster in valid:
        sim = _cosine_similarity(embedding, cluster["centroid_vector"])
        if sim > best_sim:
            best_sim = sim
            best_id = cluster["cluster_id"]

    low_confidence = best_sim < _MIN_CLUSTER_SIMILARITY
    traj_score = max(0.0, min(1.0, 1.0 - best_sim))
    return best_id, traj_score, low_confidence


def _compute_claim_novelty(
    claim_ids: list[str],
    article_qdrant_id: str,
    qdrant: QdrantClient,
    domain: str,
) -> float:
    """Score claim novelty as mean cosine distance to k nearest neighbours.

    Searches only within claims from the same domain. Excludes the
    article's own claims from the search results. Returns
    _COLD_START_CLAIM_SCORE when the claims collection is empty or all
    NN searches return no results.
    """
    if not claim_ids:
        return _COLD_START_CLAIM_SCORE

    try:
        points = qdrant.retrieve(
            collection_name="claims",
            ids=claim_ids,
            with_vectors=True,
        )
    except Exception:
        logger.warning(
            "Claim novelty: Qdrant retrieve failed", exc_info=True
        )
        return _COLD_START_CLAIM_SCORE

    if not points:
        return _COLD_START_CLAIM_SCORE

    exclude_own = Filter(
        must=[
            FieldCondition(
                key="domain",
                match=MatchValue(value=domain),
            ),
        ],
        must_not=[
            FieldCondition(
                key="article_qdrant_id",
                match=MatchValue(value=article_qdrant_id),
            ),
            FieldCondition(
                key="deferred",
                match=MatchValue(value=True),
            ),
        ],
    )

    distances: list[float] = []
    for point in points:
        try:
            response = qdrant.query_points(
                collection_name="claims",
                query=point.vector,
                query_filter=exclude_own,
                limit=_CLAIM_NOVELTY_K,
            )
            distances.extend(1.0 - r.score for r in response.points)
        except Exception:
            logger.warning(
                "Claim novelty: search failed for claim %s",
                point.id, exc_info=True,
            )

    if not distances:
        return _COLD_START_CLAIM_SCORE

    return sum(distances) / len(distances)


def _compute_bridge_score(
    concepts: list[str],
    counts: dict[tuple[str, str], int],
) -> float | None:
    """Return bridge score in [0, 1], or None if fewer than 2 concepts.

    Rare pairs (low count) score near 1.0; frequent pairs score near 0.
    Formula: mean(1 / (1 + log(1 + count))) across all concept pairs.
    """
    if len(concepts) < 2:
        return None
    pairs = list(combinations(sorted(concepts), 2))
    scores = [
        1.0 / (1.0 + math.log(1.0 + counts.get(pair, 0)))
        for pair in pairs
    ]
    return sum(scores) / len(scores)


def _compute_composite(
    trajectory_score: float,
    claim_novelty: float,
    bridge_score: float | None = None,
) -> float:
    """Return composite score using Phase 4 weights when bridge is available.

    Phase 3 (bridge_score=None): 0.40 * A + 0.60 * C
    Phase 4 (bridge_score set):  0.25 * A + 0.30 * B + 0.45 * C
    """
    if bridge_score is None:
        return (
            _W_TRAJECTORY * trajectory_score
            + _W_CLAIM_NOVELTY * claim_novelty
        )
    return (
        _W_TRAJ_P4 * trajectory_score
        + _W_BRIDGE * bridge_score
        + _W_NOVELTY_P4 * claim_novelty
    )


def _assign_label(composite: float) -> str:
    """Map a composite score to Signal / Weak Signal / Noise."""
    if composite >= _SIGNAL_THRESHOLD:
        return "Signal"
    if composite >= _WEAK_SIGNAL_THRESHOLD:
        return "Weak Signal"
    return "Noise"


def _defer_claims_in_qdrant(
    qdrant: QdrantClient,
    claim_ids: list[str],
) -> None:
    """Mark claim vectors as deferred for a Signal article pending promotion.

    Sets ``deferred=True`` in the Qdrant payload so these claims are
    excluded from novelty searches until the article is promoted. Errors
    are logged and swallowed so a Qdrant hiccup does not fail the job.
    """
    if not claim_ids:
        return
    try:
        qdrant.set_payload(
            collection_name="claims",
            payload={"deferred": True},
            points=claim_ids,
        )
    except Exception:
        logger.warning(
            "Failed to defer %d claims in Qdrant", len(claim_ids),
            exc_info=True,
        )


def _apply_plausibility_downgrade(
    label: str,
    plausibility_score: float,
) -> tuple[str, bool]:
    """Return (new_label, flagged_for_review) after applying downgrade logic.

    Signal articles with plausibility_score < threshold are downgraded to
    Weak Signal and flagged. Weak Signal articles are flagged but not further
    downgraded. All other cases are unchanged.
    """
    if plausibility_score < _PLAUSIBILITY_DOWNGRADE_THRESHOLD:
        if label == "Signal":
            return "Weak Signal", True
        if label == "Weak Signal":
            return "Weak Signal", True
    return label, False


def _call_plausibility_llm(
    oai: OpenAI,
    model: str,
    title: str,
    body: str,
    composite: float,
) -> dict | None:
    """Call LLM to assess plausibility of an article's claims.

    Returns a dict with keys plausibility_score, flags, reasoning,
    total_tokens, or None on JSON parse failure or any exception.
    """
    truncated_body = body[:_PLAUSIBILITY_BODY_CHARS]
    system_prompt = (
        "You are a scientific plausibility assessor. Evaluate whether the"
        " article's claims are grounded in credible evidence and mechanisms."
        " Return ONLY valid JSON matching this schema:\n"
        '{"plausibility_score": <float 0.0-1.0>,'
        ' "flags": <array of zero or more strings from:'
        ' ["conspiracy_framing", "no_credible_mechanism",'
        ' "low_credibility_source", "speculative_extrapolation"]>,'
        ' "reasoning": <brief explanation string>}'
    )
    user_content = (
        f"Title: {title}\n\n"
        f"Body:\n{truncated_body}\n\n"
        f"Composite signal score (context): {composite:.3f}"
    )
    try:
        response = oai.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content or ""
        # Strip markdown code fences if the model wraps JSON in ```json ... ```
        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            stripped = stripped.rsplit("```", 1)[0].strip()
        result = json.loads(stripped)
        if not isinstance(result, dict):
            raise ValueError("LLM did not return a JSON object")
        total_tokens = (
            response.usage.total_tokens if response.usage else 0
        )
        if total_tokens > _PLAUSIBILITY_TOKEN_WARN_THRESHOLD:
            logger.warning(
                "Plausibility call used %d tokens (threshold %d)",
                total_tokens, _PLAUSIBILITY_TOKEN_WARN_THRESHOLD,
            )
        result["total_tokens"] = total_tokens
        return result
    except Exception:
        logger.error(
            "Plausibility LLM call failed; skipping filter",
            exc_info=True,
        )
        return None


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
    return os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")


def _plausibility_model() -> str:
    """Return the configured LLM model for plausibility assessment."""
    return os.environ.get(
        "PLAUSIBILITY_MODEL", "anthropic/claude-sonnet-4-5"
    )


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
        body = article.get("body") or article.get("summary", "")
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
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
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
