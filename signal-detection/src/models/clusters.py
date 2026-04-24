"""Repository functions for topic_clusters and corpus_centroids."""
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
