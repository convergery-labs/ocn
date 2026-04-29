"""Database access layer for the signal-detection service."""
import os

import psycopg2
import psycopg2.extras

import db_utils
from db_utils import DuplicateError, get_db, transaction  # noqa: F401

__all__ = ["DuplicateError", "get_db", "transaction", "init_db"]


def _new_connection() -> db_utils._Connection:
    """Open a new PostgreSQL connection."""
    raw = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "signal-detection"),
        user=os.environ.get("POSTGRES_USER", "signal-detection"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        sslmode=os.environ.get("PGSSLMODE", "prefer"),
    )
    raw.cursor_factory = psycopg2.extras.RealDictCursor
    return db_utils._Connection(raw)


db_utils.configure(_new_connection)


def init_db() -> None:
    """Create all tables if they do not exist."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS classification_statuses (
                name TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topic_clusters (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                centroid_qdrant_collection TEXT NOT NULL,
                alpha REAL NOT NULL DEFAULT 0.15,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS corpus_centroids (
                id SERIAL PRIMARY KEY,
                cluster_id INTEGER NOT NULL UNIQUE
                    REFERENCES topic_clusters(id),
                embedding_model TEXT NOT NULL,
                last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                document_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'corpus_centroids_cluster_id_key'
                ) THEN
                    ALTER TABLE corpus_centroids
                    ADD CONSTRAINT corpus_centroids_cluster_id_key
                    UNIQUE (cluster_id);
                END IF;
            END$$
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS classification_jobs (
                id SERIAL PRIMARY KEY,
                run_id TEXT NOT NULL,
                status TEXT NOT NULL
                    REFERENCES classification_statuses(name),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ,
                callback_url TEXT,
                article_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS classifications (
                id SERIAL PRIMARY KEY,
                job_id INTEGER NOT NULL
                    REFERENCES classification_jobs(id),
                article_url TEXT NOT NULL,
                label TEXT NOT NULL
                    CHECK (label IN ('Signal', 'Weak Signal', 'Noise')),
                composite_score REAL NOT NULL,
                trajectory_score REAL,
                bridge_score REAL,
                claim_novelty_score REAL,
                plausibility_score REAL,
                model_embedding TEXT NOT NULL,
                model_llm TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id SERIAL PRIMARY KEY,
                classification_id INTEGER NOT NULL
                    REFERENCES classifications(id),
                claim_text TEXT NOT NULL,
                claim_embedding_id UUID NOT NULL,
                embedding_model TEXT NOT NULL
                    DEFAULT 'openai/text-embedding-3-small'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deferred_promotions (
                id SERIAL PRIMARY KEY,
                classification_id INTEGER NOT NULL
                    REFERENCES classifications(id),
                promote_at TIMESTAMPTZ NOT NULL,
                promoted_at TIMESTAMPTZ,
                final_label TEXT
                    CHECK (final_label IN ('Signal', 'Weak Signal', 'Noise'))
            )
        """)
        conn.execute(
            "ALTER TABLE corpus_centroids"
            " ADD COLUMN IF NOT EXISTS centroid_vector REAL[]"
        )
        conn.execute(
            "ALTER TABLE classifications"
            " ADD COLUMN IF NOT EXISTS article_embedding REAL[]"
        )
        conn.execute(
            "ALTER TABLE classifications"
            " ADD COLUMN IF NOT EXISTS cluster_id INTEGER"
            " REFERENCES topic_clusters(id)"
        )
        conn.execute(
            "ALTER TABLE claims"
            " ADD COLUMN IF NOT EXISTS embedding_model TEXT NOT NULL"
            " DEFAULT 'openai/text-embedding-3-small'"
        )
