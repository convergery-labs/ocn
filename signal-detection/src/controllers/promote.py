"""Orchestration for the nightly deferred corpus promotion job."""
import json
import logging
import os

import numpy as np
from qdrant_client import QdrantClient

from db import transaction
from models.claims import get_claims_for_classification
from models.clusters import (
    get_corpus_centroids_bulk,
    update_centroid_ewma,
)
from models.cooccurrences import upsert_cooccurrences
from models.jobs import get_pending_promotions, mark_promotion_done

logger = logging.getLogger(__name__)


def _cosine_similarity(
    a: list[float],
    b: list[float],
) -> float:
    """Return the cosine similarity between two equal-length vectors."""
    va = np.array(a, dtype=np.float64)
    vb = np.array(b, dtype=np.float64)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


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


def _signal_threshold() -> float:
    """Return the cosine similarity threshold above which a doc is Signal."""
    return float(os.environ.get("SIGNAL_THRESHOLD", "0.5"))


def _undefer_claims_in_qdrant(
    qdrant: QdrantClient,
    claim_ids: list[str],
    promotion_id: int,
) -> None:
    """Remove the deferred flag from confirmed-Signal claims in Qdrant."""
    if not claim_ids:
        return
    try:
        qdrant.delete_payload(
            collection_name="claims",
            keys=["deferred"],
            points=claim_ids,
        )
    except Exception:
        logger.warning(
            "Failed to un-defer claims for promotion %d",
            promotion_id, exc_info=True,
        )


def _delete_claims_from_qdrant(
    qdrant: QdrantClient,
    claim_ids: list[str],
    promotion_id: int,
) -> None:
    """Permanently remove Noise-demoted claim vectors from Qdrant."""
    if not claim_ids:
        return
    try:
        qdrant.delete(
            collection_name="claims",
            points_selector=claim_ids,
        )
    except Exception:
        logger.warning(
            "Failed to delete claims for promotion %d",
            promotion_id, exc_info=True,
        )


def promote_deferred_corpus() -> dict[str, int]:
    """Process all pending deferred_promotions and update centroids.

    For each pending promotion:
    - Computes cosine similarity of the stored article embedding vs the
      current EWMA centroid for the article's cluster.
    - Above threshold: updates the centroid (EWMA), marks final_label=Signal.
    - At or below threshold: marks final_label=Noise (false positive; centroid
      is not updated).

    Each promotion is committed independently so one failure does not abort
    the batch.

    Returns a dict with keys ``processed``, ``promoted``, ``discarded``,
    ``skipped`` (missing embedding or centroid).
    """
    pending = get_pending_promotions()
    threshold = _signal_threshold()
    qdrant = _qdrant_client()

    unique_cluster_ids: list[int] = list({
        row["cluster_id"]
        for row in pending
        if row["cluster_id"] is not None
    })
    centroids_by_cluster = get_corpus_centroids_bulk(unique_cluster_ids)

    promoted = 0
    discarded = 0
    skipped = 0

    for row in pending:
        promotion_id: int = row["promotion_id"]
        cluster_id: int | None = row["cluster_id"]
        embedding: list[float] | None = row["article_embedding"]

        if cluster_id is None or embedding is None:
            logger.warning(
                "Skipping promotion %d: missing cluster_id or embedding",
                promotion_id,
            )
            skipped += 1
            continue

        centroid_row = centroids_by_cluster.get(cluster_id)
        if centroid_row is None or centroid_row.get("centroid_vector") is None:
            logger.warning(
                "Skipping promotion %d: no centroid for cluster %d",
                promotion_id,
                cluster_id,
            )
            skipped += 1
            continue

        centroid_vec: list[float] = centroid_row["centroid_vector"]
        alpha: float = centroid_row["alpha"]
        sim = _cosine_similarity(embedding, centroid_vec)

        classification_id: int = row["classification_id"]
        concepts: list[str] = json.loads(row.get("concepts") or "[]")
        claims = get_claims_for_classification(classification_id)
        claim_ids = [c["claim_embedding_id"] for c in claims]

        try:
            with transaction():
                if sim > threshold:
                    update_centroid_ewma(cluster_id, embedding, alpha)
                    mark_promotion_done(promotion_id, "Signal")
                    promoted += 1
                    logger.info(
                        "Promotion %d → Signal (sim=%.4f)", promotion_id, sim
                    )
                else:
                    mark_promotion_done(promotion_id, "Noise")
                    discarded += 1
                    logger.info(
                        "Promotion %d → Noise (sim=%.4f)", promotion_id, sim
                    )
        except Exception:
            logger.exception(
                "Failed to process promotion %d", promotion_id
            )
            skipped += 1
            continue

        # Corpus mutations outside the DB transaction - best-effort.
        if sim > threshold:
            upsert_cooccurrences(concepts)
            _undefer_claims_in_qdrant(qdrant, claim_ids, promotion_id)
        else:
            _delete_claims_from_qdrant(qdrant, claim_ids, promotion_id)

    return {
        "processed": len(pending),
        "promoted": promoted,
        "discarded": discarded,
        "skipped": skipped,
    }
