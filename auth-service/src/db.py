"""Database access layer for auth-service."""
import os

import psycopg2
import psycopg2.extras

import db_utils
from db_utils import DuplicateError, get_db  # noqa: F401

__all__ = ["DuplicateError", "get_db", "init_db"]


def _new_connection() -> db_utils._Connection:
    """Open a new PostgreSQL connection using AUTH_POSTGRES_* env vars."""
    raw = psycopg2.connect(
        host=os.environ.get("AUTH_POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("AUTH_POSTGRES_PORT", "5432")),
        dbname=os.environ.get("AUTH_POSTGRES_DB", "auth-service"),
        user=os.environ.get("AUTH_POSTGRES_USER", "auth-service"),
        password=os.environ.get("AUTH_POSTGRES_PASSWORD", ""),
        sslmode=os.environ.get("PGSSLMODE", "prefer"),
    )
    raw.cursor_factory = psycopg2.extras.RealDictCursor
    return db_utils._Connection(raw)


db_utils.configure(_new_connection)


def init_db() -> None:
    """Create all auth-service tables if they do not exist."""
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
                id   SERIAL PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      TEXT        NOT NULL UNIQUE,
                email         TEXT        NOT NULL UNIQUE,
                password_hash TEXT        NOT NULL,
                role          TEXT        NOT NULL REFERENCES roles(name)
                                          DEFAULT 'user',
                is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMPTZ
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_domains (
                user_id   INTEGER NOT NULL REFERENCES users(id),
                domain_id INTEGER NOT NULL REFERENCES domains(id),
                PRIMARY KEY (user_id, domain_id)
            )
        """)
