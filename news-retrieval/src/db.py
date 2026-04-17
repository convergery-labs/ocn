"""Database access layer for the OCN news aggregator."""
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
                 values clause, e.g.
                 ``INSERT INTO t (a, b) VALUES %s``.
            data: Sequence of row tuples to insert.
            template: Optional per-row template; passed through to
                      ``execute_values``.

        Returns:
            The cursor after execution; call ``.fetchall()`` to
            consume ``RETURNING`` results.
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

        Accepts portable placeholder styles and converts them to the
        psycopg2 format before execution:
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
        dbname=os.environ.get("POSTGRES_DB", "ocn"),
        user=os.environ.get("POSTGRES_USER", "ocn"),
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
        yield  # already inside a transaction — join it
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
            CREATE TABLE IF NOT EXISTS roles (
                name TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            INSERT INTO roles (name) VALUES ('admin'), ('user')
            ON CONFLICT (name) DO NOTHING
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id           SERIAL PRIMARY KEY,
                key_hash     TEXT        NOT NULL UNIQUE,
                label        TEXT,
                role         TEXT        NOT NULL REFERENCES roles(name),
                created_by   INTEGER     REFERENCES api_keys(id),
                created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMPTZ
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS domains (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL UNIQUE,
                slug        TEXT NOT NULL UNIQUE,
                description TEXT,
                created_by  INTEGER REFERENCES api_keys(id),
                created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS frequencies (
                id            SERIAL PRIMARY KEY,
                name          TEXT    NOT NULL UNIQUE,
                min_days_back INTEGER NOT NULL,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id           SERIAL PRIMARY KEY,
                url          TEXT    NOT NULL UNIQUE,
                domain_id    INTEGER NOT NULL REFERENCES domains(id),
                frequency_id INTEGER NOT NULL REFERENCES frequencies(id),
                name         TEXT,
                description  TEXT,
                created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("DROP TABLE IF EXISTS taxonomies")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_statuses (
                name TEXT PRIMARY KEY
            )
        """)
        conn.execute("""
            INSERT INTO run_statuses (name)
            VALUES ('running'), ('completed'), ('failed')
            ON CONFLICT (name) DO NOTHING
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id            SERIAL PRIMARY KEY,
                name          TEXT        NOT NULL,
                domain        TEXT        NOT NULL,
                started_at    TIMESTAMPTZ NOT NULL
                              DEFAULT CURRENT_TIMESTAMP,
                completed_at  TIMESTAMPTZ,
                status        TEXT        NOT NULL DEFAULT 'running'
                              REFERENCES run_statuses(name),
                days_back     INTEGER     NOT NULL,
                max_articles  INTEGER,
                focus         TEXT,
                article_count INTEGER,
                summary       TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id          SERIAL PRIMARY KEY,
                run_id      INTEGER NOT NULL REFERENCES runs(id),
                url         TEXT,
                title       TEXT,
                summary     TEXT,
                source      TEXT,
                published   TEXT,
                created_at  TIMESTAMPTZ NOT NULL
                            DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migrations for existing deployments
        conn.execute(
            "ALTER TABLE runs"
            " ADD COLUMN IF NOT EXISTS article_count INTEGER"
        )
        conn.execute(
            "ALTER TABLE runs ADD COLUMN IF NOT EXISTS summary TEXT"
        )
        conn.execute(
            "ALTER TABLE runs DROP COLUMN IF EXISTS category_count"
        )
        conn.execute(
            "ALTER TABLE runs DROP COLUMN IF EXISTS report_count"
        )
        conn.execute(
            "ALTER TABLE runs DROP COLUMN IF EXISTS summary_depth"
        )
        conn.execute("DROP TABLE IF EXISTS reports")
        conn.execute(
            "ALTER TABLE articles"
            " DROP COLUMN IF EXISTS category_id"
        )
        conn.execute("DROP TABLE IF EXISTS categories")
        # Add FK from runs.status to run_statuses on existing deployments
        conn.execute("""
            DO $$ BEGIN
              ALTER TABLE runs ADD CONSTRAINT runs_status_fkey
                FOREIGN KEY (status) REFERENCES run_statuses(name);
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
        """)
        conn.execute(
            "ALTER TABLE domains"
            " ADD COLUMN IF NOT EXISTS created_by"
            " INTEGER REFERENCES api_keys(id)"
        )
