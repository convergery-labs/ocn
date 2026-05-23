"""Database access layer for the signal-detection-agent service."""
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
    """Create agent tables if they do not exist."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_job_statuses (
                status TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_jobs (
                id           SERIAL PRIMARY KEY,
                news_run_id  INTEGER,
                domain       TEXT NOT NULL,
                status       TEXT NOT NULL REFERENCES agent_job_statuses(status),
                article_count INTEGER NOT NULL DEFAULT 0,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_classifications (
                id               SERIAL PRIMARY KEY,
                job_id           INTEGER NOT NULL REFERENCES agent_jobs(id),
                article_id       INTEGER,
                url              TEXT,
                title            TEXT,
                signal_detection TEXT NOT NULL
                    CHECK (signal_detection IN ('signal', 'weak_signal', 'noise')),
                signal_score     NUMERIC(5,4) NOT NULL,
                signal_reason    TEXT,
                materiality      TEXT NOT NULL
                    CHECK (materiality IN ('high', 'medium', 'low', 'none')),
                category         TEXT NOT NULL,
                entities_json    TEXT NOT NULL DEFAULT '[]',
                stored_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
