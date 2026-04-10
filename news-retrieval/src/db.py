"""Database access layer for the OCN news aggregator."""
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator

DB_PATH = os.environ.get("DB_PATH", "/app/data/sources.db")

_local = threading.local()


def _new_connection() -> sqlite3.Connection:
    """Open a raw database connection with FK enforcement."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a database connection.

    If called inside a ``transaction()`` block the ambient connection
    is reused and lifecycle management is left to the outer context.
    Otherwise a fresh connection is opened, committed on clean exit,
    and closed on return.
    """
    ambient = getattr(_local, "conn", None)
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
    if getattr(_local, "conn", None) is not None:
        yield  # already inside a transaction — join it
        return
    conn = _new_connection()
    _local.conn = conn
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        _local.conn = None


def init_db() -> None:
    """Create all tables if they do not exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS domains (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                slug        TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS frequencies (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL UNIQUE,
                min_days_back INTEGER NOT NULL,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sources (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                url          TEXT    NOT NULL UNIQUE,
                domain_id    INTEGER NOT NULL REFERENCES domains(id),
                frequency_id INTEGER NOT NULL REFERENCES frequencies(id),
                name         TEXT,
                description  TEXT,
                created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS taxonomies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                domain_id   INTEGER NOT NULL REFERENCES domains(id),
                category    TEXT    NOT NULL,
                position    INTEGER NOT NULL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                UNIQUE(domain_id, category)
            );
        """)
