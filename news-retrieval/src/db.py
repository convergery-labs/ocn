"""Database access layer for the OCN news aggregator."""
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
        dbname=os.environ.get("POSTGRES_DB", "news-retrieval"),
        user=os.environ.get("POSTGRES_USER", "news-retrieval"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        sslmode=os.environ.get("PGSSLMODE", "prefer"),
    )
    raw.cursor_factory = psycopg2.extras.RealDictCursor
    return db_utils._Connection(raw)


db_utils.configure(_new_connection)


def init_db() -> None:
    """Create all tables if they do not exist."""
    with get_db() as conn:
        # Drop legacy tables that are now owned by auth-service
        conn.execute("DROP TABLE IF EXISTS api_keys CASCADE")
        conn.execute("DROP TABLE IF EXISTS roles CASCADE")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS domains (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL UNIQUE,
                slug        TEXT NOT NULL UNIQUE,
                description TEXT,
                created_by  INTEGER,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_key_domains (
                api_key_id INTEGER NOT NULL,
                domain_id  INTEGER NOT NULL REFERENCES domains(id),
                PRIMARY KEY (api_key_id, domain_id)
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
                no_fetch     BOOLEAN NOT NULL DEFAULT FALSE,
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
                summary       TEXT,
                callback_url  TEXT,
                model         TEXT        NOT NULL
                              DEFAULT 'inclusionai/ling-2.6-flash:free'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id          SERIAL PRIMARY KEY,
                run_id      INTEGER NOT NULL REFERENCES runs(id),
                url         TEXT,
                title       TEXT,
                summary     TEXT,
                body        TEXT,
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
            "ALTER TABLE runs"
            " ADD COLUMN IF NOT EXISTS callback_url TEXT"
        )
        conn.execute(
            "ALTER TABLE runs"
            " ADD COLUMN IF NOT EXISTS model TEXT NOT NULL"
            " DEFAULT 'inclusionai/ling-2.6-flash:free'"
        )
        conn.execute(
            "ALTER TABLE articles"
            " ADD COLUMN IF NOT EXISTS body TEXT"
        )
        conn.execute(
            "ALTER TABLE sources"
            " ADD COLUMN IF NOT EXISTS no_fetch"
            " BOOLEAN NOT NULL DEFAULT FALSE"
        )
