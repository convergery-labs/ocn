"""Orchestrator for historical ingestion: fetch, deduplicate, embed, upsert."""
import logging
import os
import uuid
from datetime import date

from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from historical_ingestion.adapters.base import AbstractHistoricalAdapter
from historical_ingestion.schema import HistoricalDocument

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE = 50
_VECTOR_SIZE = 3072
_EMBED_COST_PER_M_TOKENS = 0.13  # USD, text-embedding-3-large


def run_ingestion(
    adapter: AbstractHistoricalAdapter,
    query: str,
    date_from: date,
    date_to: date,
    collection: str,
    dry_run: bool = False,
) -> dict[str, int]:
    """Fetch, deduplicate, embed, and upsert historical documents to Qdrant.

    Args:
        adapter: The source adapter (GDELT, arXiv, …).
        query: Keyword/phrase to search for.
        date_from: Inclusive start date.
        date_to: Inclusive end date.
        collection: Target Qdrant collection name.
        dry_run: If True, skip embedding and upsert; just report counts.

    Returns:
        Dict with keys ``total``, ``new``, ``skipped``, ``failed``.
    """
    docs = adapter.fetch(query, date_from, date_to)
    total = len(docs)
    logger.info("Fetched %d documents from adapter", total)

    if not docs:
        return {"total": 0, "new": 0, "skipped": 0, "failed": 0}

    if dry_run:
        _log_cost_estimate(docs)
        return {"total": total, "new": total, "skipped": 0, "failed": 0}

    qdrant = _qdrant_client()
    _ensure_collection(qdrant, collection)

    point_ids = [_url_to_point_id(doc.url) for doc in docs]
    existing_ids = _fetch_existing_ids(qdrant, collection, point_ids)

    new_docs = [
        doc for doc, pid in zip(docs, point_ids) if pid not in existing_ids
    ]
    skipped = total - len(new_docs)

    logger.info(
        "Deduplication: %d new, %d already in Qdrant", len(new_docs), skipped
    )

    failed = _embed_and_upsert(qdrant, collection, new_docs)

    return {
        "total": total,
        "new": len(new_docs),
        "skipped": skipped,
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _qdrant_client() -> QdrantClient:
    """Return a configured Qdrant client."""
    return QdrantClient(
        host=os.environ.get("QDRANT_HOST", "qdrant"),
        port=int(os.environ.get("QDRANT_PORT", "6333")),
    )


def _openai_client() -> OpenAI:
    """Return an OpenAI client pointed at OpenRouter."""
    return OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )


def _embedding_model() -> str:
    """Return the configured embedding model name."""
    return os.environ.get(
        "EMBEDDING_MODEL", "openai/text-embedding-3-large"
    )


def _url_to_point_id(url: str) -> str:
    """Return a deterministic UUID5 point ID for a URL."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url))


def _ensure_collection(client: QdrantClient, name: str) -> None:
    """Create *name* in Qdrant if it does not already exist."""
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=_VECTOR_SIZE,
                distance=Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection: %s", name)


def _fetch_existing_ids(
    client: QdrantClient,
    collection: str,
    point_ids: list[str],
) -> set[str]:
    """Return the subset of *point_ids* already present in *collection*."""
    if not point_ids:
        return set()
    results = client.retrieve(
        collection_name=collection,
        ids=point_ids,
        with_vectors=False,
    )
    return {str(r.id) for r in results}


def _embed_batch(
    client: OpenAI,
    model: str,
    texts: list[str],
) -> list[list[float]]:
    """Embed a batch of texts via the OpenRouter API."""
    truncated = [t[:30_000] for t in texts]
    response = client.embeddings.create(model=model, input=truncated)
    return [item.embedding for item in response.data]


def _embed_and_upsert(
    qdrant: QdrantClient,
    collection: str,
    docs: list[HistoricalDocument],
) -> int:
    """Embed *docs* in batches and upsert to Qdrant. Returns failure count."""
    oai = _openai_client()
    model = _embedding_model()
    failed = 0
    total_chars = sum(len(d.body) for d in docs)
    _log_cost_estimate(docs)

    for i in range(0, len(docs), _EMBED_BATCH_SIZE):
        batch = docs[i: i + _EMBED_BATCH_SIZE]
        try:
            embeddings = _embed_batch(oai, model, [d.body for d in batch])
        except Exception:
            logger.exception(
                "Embedding failed for batch %d–%d", i, i + len(batch)
            )
            failed += len(batch)
            continue

        points = [
            PointStruct(
                id=_url_to_point_id(doc.url),
                vector=emb,
                payload={
                    "url": doc.url,
                    "source_adapter": doc.source_adapter,
                    "published_date": str(doc.published_date),
                    "label": None,
                },
            )
            for doc, emb in zip(batch, embeddings)
        ]

        try:
            qdrant.upsert(collection_name=collection, points=points)
        except Exception:
            logger.exception(
                "Qdrant upsert failed for batch %d–%d", i, i + len(batch)
            )
            failed += len(batch)
            continue

        logger.info(
            "Upserted %d/%d documents", min(i + _EMBED_BATCH_SIZE, len(docs)),
            len(docs),
        )

    return failed


def _log_cost_estimate(docs: list[HistoricalDocument]) -> None:
    """Log an estimated embedding cost for *docs*."""
    total_chars = sum(len(d.body) for d in docs)
    approx_tokens = total_chars / 4
    cost_usd = approx_tokens / 1_000_000 * _EMBED_COST_PER_M_TOKENS
    logger.info(
        "Embedding cost estimate: ~%.0f tokens (~$%.4f USD)",
        approx_tokens,
        cost_usd,
    )
