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
            CREATE TABLE IF NOT EXISTS domains (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL UNIQUE,
                slug        TEXT NOT NULL UNIQUE,
                description TEXT,
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS taxonomies (
                id          SERIAL PRIMARY KEY,
                domain_id   INTEGER NOT NULL REFERENCES domains(id),
                category    TEXT    NOT NULL,
                position    INTEGER NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(domain_id, category)
            )
        """)
