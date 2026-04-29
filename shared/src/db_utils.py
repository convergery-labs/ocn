"""Shared PostgreSQL connection utilities for OCN services.

Services register their own connection factory via ``configure()``
and then re-export ``get_db``, ``transaction``, and ``DuplicateError``
from their local ``db`` module so that all other imports are unchanged.
"""
import contextvars
import re
from contextlib import contextmanager
from typing import Callable, Generator

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

_connection_factory: Callable[[], _Connection] | None = None


def configure(factory: Callable[[], _Connection]) -> None:
    """Register the connection factory for this service process.

    Must be called once at module load time from the service's
    ``db.py`` before any ``get_db()`` or ``transaction()`` call.
    """
    global _connection_factory
    _connection_factory = factory


def _make_connection() -> _Connection:
    """Invoke the registered factory or raise if unconfigured."""
    if _connection_factory is None:
        raise RuntimeError(
            "db_utils not configured; call db_utils.configure() first"
        )
    return _connection_factory()


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
    conn = _make_connection()
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
    conn = _make_connection()
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
