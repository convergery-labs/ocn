"""Database access layer for the research-universe service."""
import os

import psycopg2
import psycopg2.extras

import db_utils
from db_utils import DuplicateError, get_db, transaction  # noqa: F401

__all__ = ["DuplicateError", "get_db", "transaction", "init_db"]


def _new_connection() -> db_utils._Connection:
    raw = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "research-universe"),
        user=os.environ.get("POSTGRES_USER", "research-universe"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        sslmode=os.environ.get("PGSSLMODE", "prefer"),
    )
    raw.cursor_factory = psycopg2.extras.RealDictCursor
    return db_utils._Connection(raw)


db_utils.configure(_new_connection)


def init_db() -> None:
    """Create all tables and indexes if they do not exist."""
    with get_db() as conn:
        # Fuzzy search support
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

        # ------------------------------------------------------------------ #
        # Taxonomy - categories and subcategories                             #
        # ------------------------------------------------------------------ #
        conn.execute("""
            CREATE TABLE IF NOT EXISTS universe_taxonomy (
                id             SERIAL PRIMARY KEY,
                type           TEXT NOT NULL CHECK (type IN ('category', 'subcategory')),
                name           TEXT NOT NULL,
                parent_id      INTEGER REFERENCES universe_taxonomy(id),
                agent_proposed BOOLEAN NOT NULL DEFAULT FALSE,
                created_by     TEXT,
                created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (type, name)
            )
        """)

        # ------------------------------------------------------------------ #
        # Companies - one row per company                                     #
        # ------------------------------------------------------------------ #
        conn.execute("""
            CREATE TABLE IF NOT EXISTS universe_companies (
                id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                company_name          TEXT NOT NULL,
                ticker                TEXT NOT NULL,
                market                TEXT NOT NULL,
                country               TEXT NOT NULL,
                website               TEXT NOT NULL,

                -- Arrays: usually length 1, occasionally 2 for multi-category companies
                category_ids          INTEGER[] NOT NULL,
                subcategory_ids       INTEGER[] NOT NULL,

                -- Only populated when category_ids has more than one entry
                multi_category_reason TEXT,

                -- Provenance
                status                TEXT NOT NULL DEFAULT 'verified'
                                      CHECK (status IN ('pending_review', 'verified')),
                agent_added           BOOLEAN NOT NULL DEFAULT FALSE,
                added_by              TEXT,
                added_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                verified_by           TEXT,
                verified_at           TIMESTAMPTZ,

                UNIQUE (company_name)
            )
        """)

        # Trigram index for fuzzy company name search
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_companies_name_trgm
                ON universe_companies USING gin (company_name gin_trgm_ops)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_companies_ticker
                ON universe_companies (ticker)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_companies_status
                ON universe_companies (status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_companies_agent_added
                ON universe_companies (agent_added)
        """)
        # GIN index for ANY(category_ids) lookups - critical for discovery dedup at scale
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_companies_category_ids
                ON universe_companies USING gin (category_ids)
        """)
        # Partial index - speeds up pending review queue at high pending counts
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_companies_pending
                ON universe_companies (added_at DESC)
                WHERE status = 'pending_review'
        """)

        # ------------------------------------------------------------------ #
        # Users - API key auth (Google OAuth slots in later via google_id)   #
        # ------------------------------------------------------------------ #
        conn.execute("""
            CREATE TABLE IF NOT EXISTS universe_users (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name            TEXT NOT NULL,
                email           TEXT NOT NULL UNIQUE,
                api_key_hash    TEXT UNIQUE,        -- bcrypt hash; NULL once on Google OAuth
                google_id       TEXT UNIQUE,        -- future Google OAuth subject
                is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at    TIMESTAMPTZ
            )
        """)
        conn.execute("ALTER TABLE universe_users ADD COLUMN IF NOT EXISTS password_hash TEXT")
        conn.execute("ALTER TABLE universe_users ADD COLUMN IF NOT EXISTS session_token TEXT UNIQUE")
        conn.execute("ALTER TABLE universe_users ADD COLUMN IF NOT EXISTS session_expires_at TIMESTAMPTZ")

        # ------------------------------------------------------------------ #
        # Conversations - persisted chat history per user                     #
        # ------------------------------------------------------------------ #
        conn.execute("""
            CREATE TABLE IF NOT EXISTS universe_conversations (
                id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id    TEXT NOT NULL,
                messages   JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_user_id
                ON universe_conversations (user_id)
        """)

        # ------------------------------------------------------------------ #
        # Scan jobs - universe discovery job state                           #
        # ------------------------------------------------------------------ #
        conn.execute("""
            CREATE TABLE IF NOT EXISTS universe_scan_jobs (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                status              TEXT NOT NULL DEFAULT 'running'
                                    CHECK (status IN ('running', 'completed', 'failed')),
                triggered_by        TEXT,
                categories_total    INTEGER NOT NULL DEFAULT 0,
                categories_done     INTEGER NOT NULL DEFAULT 0,
                companies_proposed  INTEGER NOT NULL DEFAULT 0,
                companies_skipped   INTEGER NOT NULL DEFAULT 0,
                category_results    JSONB NOT NULL DEFAULT '[]'::jsonb,
                started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at        TIMESTAMPTZ
            )
        """)

        # Add last_enriched_at to taxonomy if not present (idempotent)
        conn.execute("""
            ALTER TABLE universe_taxonomy
            ADD COLUMN IF NOT EXISTS last_enriched_at TIMESTAMPTZ
        """)

        # ------------------------------------------------------------------ #
        # Startup cleanup                                                      #
        # ------------------------------------------------------------------ #

        # Reset scan jobs stuck in 'running' for more than 2 hours
        conn.execute("""
            UPDATE universe_scan_jobs
               SET status = 'failed', completed_at = NOW()
             WHERE status = 'running'
               AND started_at < NOW() - INTERVAL '2 hours'
        """)

        # Prune conversation history older than 30 days
        conn.execute("""
            DELETE FROM universe_conversations
             WHERE updated_at < NOW() - INTERVAL '30 days'
        """)

        # Prune completed/failed scan jobs older than 90 days
        conn.execute("""
            DELETE FROM universe_scan_jobs
             WHERE status IN ('completed', 'failed')
               AND started_at < NOW() - INTERVAL '90 days'
        """)
