"""Database access layer for auth-service."""
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
            DuplicateError: if the statement violates a UNIQUE
                constraint.
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
    """Open a new PostgreSQL connection using AUTH_POSTGRES_* env vars."""
    raw = psycopg2.connect(
        host=os.environ.get("AUTH_POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("AUTH_POSTGRES_PORT", "5432")),
        dbname=os.environ.get("AUTH_POSTGRES_DB", "auth-service"),
        user=os.environ.get("AUTH_POSTGRES_USER", "auth-service"),
        password=os.environ.get("AUTH_POSTGRES_PASSWORD", ""),
    )
    raw.cursor_factory = psycopg2.extras.RealDictCursor
    return _Connection(raw)


@contextmanager
def get_db() -> Generator[_Connection, None, None]:
    """Yield a database connection.

    Reuses the ambient connection if called inside a ``transaction()``
    block; otherwise opens, commits, and closes a fresh connection.
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


def init_db() -> None:
    """Create the roles and api_keys tables if they do not exist."""
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
