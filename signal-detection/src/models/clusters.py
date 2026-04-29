"""Repository functions for topic_clusters and corpus_centroids."""
from typing import Any

from db import get_db


def upsert_topic_cluster(
    name: str,
    slug: str,
    collection: str,
    alpha: float = 0.15,
) -> int:
    """Insert or update a topic_clusters row; return its id."""
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO topic_clusters
                (name, slug, centroid_qdrant_collection, alpha)
            VALUES (:name, :slug, :collection, :alpha)
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                centroid_qdrant_collection = EXCLUDED.centroid_qdrant_collection,
                alpha = EXCLUDED.alpha
            RETURNING id
            """,
            {
                "name": name,
                "slug": slug,
                "collection": collection,
                "alpha": alpha,
            },
        ).fetchone()
    return row["id"]


def get_corpus_centroid(cluster_id: int) -> dict[str, Any] | None:
    """Return the corpus_centroids row (with alpha) for cluster_id, or None."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT cc.*, tc.alpha
            FROM corpus_centroids cc
            JOIN topic_clusters tc ON tc.id = cc.cluster_id
            WHERE cc.cluster_id = :cluster_id
            """,
            {"cluster_id": cluster_id},
        ).fetchone()
    return dict(row) if row else None


def get_corpus_centroids_bulk(
    cluster_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """Return a {cluster_id: row} mapping for all given cluster_ids.

    Fetches all matching corpus_centroids rows (with alpha) in a single
    query using an IN clause.  Missing cluster_ids are simply absent from
    the returned dict.
    """
    if not cluster_ids:
        return {}
    placeholders = ", ".join(["%s"] * len(cluster_ids))
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT cc.*, tc.alpha
            FROM corpus_centroids cc
            JOIN topic_clusters tc ON tc.id = cc.cluster_id
            WHERE cc.cluster_id IN ({placeholders})
            """,
            cluster_ids,
        ).fetchall()
    return {dict(row)["cluster_id"]: dict(row) for row in rows}


def update_centroid_ewma(
    cluster_id: int,
    embedding: list[float],
    alpha: float,
) -> None:
    """Apply the EWMA update to the stored centroid and increment document_count.

    centroid_t = alpha * embedding + (1 - alpha) * centroid_{t-1}
    Seeds with the incoming embedding when no centroid vector exists yet.
    Must be called inside a transaction() block so the update is atomic
    with the accompanying classification insert.
    """
    row = get_corpus_centroid(cluster_id)
    if row is None:
        raise ValueError(
            f"No corpus_centroids row for cluster_id={cluster_id}"
        )
    existing: list[float] | None = row.get("centroid_vector")
    if existing is None:
        updated = embedding
    else:
        updated = [
            alpha * n + (1.0 - alpha) * c
            for n, c in zip(embedding, existing)
        ]
    with get_db() as conn:
        conn.execute(
            """
            UPDATE corpus_centroids
            SET centroid_vector = :vec,
                document_count = document_count + 1,
                last_updated_at = NOW()
            WHERE cluster_id = :cluster_id
            """,
            {
                "vec": updated,
                "cluster_id": cluster_id,
            },
        )


def upsert_corpus_centroid(
    cluster_id: int,
    embedding_model: str,
    document_count: int,
) -> None:
    """Insert or update a corpus_centroids row for a cluster."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO corpus_centroids
                (cluster_id, embedding_model, document_count)
            VALUES (:cluster_id, :embedding_model, :document_count)
            ON CONFLICT (cluster_id) DO UPDATE SET
                embedding_model = EXCLUDED.embedding_model,
                document_count = EXCLUDED.document_count,
                last_updated_at = NOW()
            """,
            {
                "cluster_id": cluster_id,
                "embedding_model": embedding_model,
                "document_count": document_count,
            },
        )
