"""Database access layer for the signal-detection service."""
import contextvars
import os
import re
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.errors
import psycopg2.extensions
import psycopg2.extras

_NAMED_PARAM_RE = re.compile(r"(?<!:):(\w+)")


class DuplicateError(Exception):
    """Raised when an INSERT violates a UNIQUE constraint."""


class _Connection:
    """Thin psycopg2 wrapper that exposes a sqlite3-style execute().

    Converts ``psycopg2.errors.UniqueViolation`` to ``DuplicateError``
    so callers never need to import psycopg2 directly.
    """

    def __init__(self, conn: psycopg2.extensions.connection) -> None:
        """Wrap a raw psycopg2 connection."""
        self._conn = conn

    def execute_values(
        self,
        sql: str,
        data: list,
        template: str | None = None,
    ) -> psycopg2.extensions.cursor:
        """Execute a batch INSERT via psycopg2.extras.execute_values.

        Args:
            sql: INSERT statement with a ``%s`` placeholder for the
                 values clause.
            data: Sequence of row tuples to insert.
            template: Optional per-row template.

        Returns:
            The cursor after execution.
        """
        cur = self._conn.cursor()
        psycopg2.extras.execute_values(
            cur, sql, data, template=template
        )
        return cur

    def execute(
        self,
        sql: str,
        params: tuple | dict | None = None,
    ) -> psycopg2.extensions.cursor:
        """Execute *sql* with *params* and return the cursor.

        Accepts portable placeholder styles:
        - ``?``     (positional) → ``%s``
        - ``:name`` (named)      → ``%(name)s``

        Raises:
            DuplicateError: if the statement violates a UNIQUE constraint.
        """
        if isinstance(params, dict):
            sql = _NAMED_PARAM_RE.sub(r"%(\1)s", sql)
        else:
            sql = sql.replace("?", "%s")
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
        except psycopg2.errors.UniqueViolation as exc:
            raise DuplicateError(str(exc)) from exc
        return cur

    def commit(self) -> None:
        """Commit the current transaction."""
        self._conn.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        self._conn.rollback()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()


_ambient_conn: contextvars.ContextVar[
    _Connection | None
] = contextvars.ContextVar("ambient_conn", default=None)


def _new_connection() -> _Connection:
    """Open a new PostgreSQL connection."""
    raw = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "signal-detection"),
        user=os.environ.get("POSTGRES_USER", "signal-detection"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
    )
    raw.cursor_factory = psycopg2.extras.RealDictCursor
    return _Connection(raw)


@contextmanager
def get_db() -> Generator[_Connection, None, None]:
    """Yield a database connection.

    If called inside a ``transaction()`` block the ambient connection
    is reused and lifecycle management is left to the outer context.
    Otherwise a fresh connection is opened, committed on clean exit,
    and closed on return.
    """
    ambient = _ambient_conn.get()
    if ambient is not None:
        yield ambient
        return
    conn = _new_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def transaction() -> Generator[None, None, None]:
    """Run a block atomically in a single database transaction.

    All ``get_db()`` calls within this block share one connection.
    Nested ``transaction()`` calls join the outermost transaction.
    Commits on clean exit; rolls back the entire block on any error.
    """
    if _ambient_conn.get() is not None:
        yield
        return
    conn = _new_connection()
    token = _ambient_conn.set(conn)
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        _ambient_conn.reset(token)


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
