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
        conn.execute("""
            ALTER TABLE agent_classifications
                ADD COLUMN IF NOT EXISTS base_signal_detection TEXT,
                ADD COLUMN IF NOT EXISTS base_signal_score FLOAT,
                ADD COLUMN IF NOT EXISTS novelty_basis TEXT,
                ADD COLUMN IF NOT EXISTS novelty TEXT,
                ADD COLUMN IF NOT EXISTS confidence_basis TEXT,
                ADD COLUMN IF NOT EXISTS confidence TEXT,
                ADD COLUMN IF NOT EXISTS refinement_reason TEXT
        """)
        conn.execute("""
            ALTER TABLE agent_classifications
                ADD COLUMN IF NOT EXISTS entity_names_normalized TEXT[] DEFAULT '{}'
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_names_gin
                ON agent_classifications USING GIN(entity_names_normalized)
        """)
        conn.execute("""
            ALTER TABLE agent_classifications
                ADD COLUMN IF NOT EXISTS pre_verification_score FLOAT,
                ADD COLUMN IF NOT EXISTS verification_qa JSONB
        """)
        conn.execute("""
            ALTER TABLE agent_classifications
                ADD COLUMN IF NOT EXISTS published TIMESTAMPTZ
        """)
        conn.execute("""
            UPDATE agent_classifications
            SET entity_names_normalized = ARRAY(
                SELECT LOWER(e->>'name')
                FROM jsonb_array_elements(entities_json::jsonb) e
                WHERE e->>'name' IS NOT NULL
            )
            WHERE entity_names_normalized IS NULL OR entity_names_normalized = '{}'
        """)
        conn.execute("""
            ALTER TABLE agent_classifications
                ALTER COLUMN category DROP NOT NULL,
                ALTER COLUMN materiality DROP NOT NULL
        """)
        conn.execute("""
            ALTER TABLE agent_classifications
                ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'news',
                ADD COLUMN IF NOT EXISTS source_id TEXT
        """)
        # company_rank/company_percentile: added for a company-relative ranking
        # feature that was deprioritized before any code ever read or wrote
        # them - confirmed unreferenced anywhere outside this migration, so
        # dropping rather than leaving them as permanently-empty dead columns.
        conn.execute("""
            ALTER TABLE agent_classifications
                DROP COLUMN IF EXISTS company_rank,
                DROP COLUMN IF EXISTS company_percentile
        """)
        # source_type's allowed set grows as new domains are added (news, sec_filing,
        # geopolitical, company_specific, ...) - drop/recreate rather than ALTER,
        # since Postgres has no ALTER CHECK. Add new values here, not a new migration.
        conn.execute("""
            ALTER TABLE agent_classifications
                DROP CONSTRAINT IF EXISTS agent_classifications_source_type_check
        """)
        conn.execute("""
            ALTER TABLE agent_classifications
                ADD CONSTRAINT agent_classifications_source_type_check
                    CHECK (source_type IN ('news', 'sec_filing', 'geopolitical', 'company_specific', 'taiwan_market_signal'))
        """)
        conn.execute("""
            ALTER TABLE agent_classifications
                ADD COLUMN IF NOT EXISTS concreteness FLOAT,
                ADD COLUMN IF NOT EXISTS economic_scale FLOAT
        """)
        # metadata: source-specific fields that don't warrant their own typed
        # column, same rationale as news-retrieval's articles.metadata - the
        # taiwan_market_signal source_type is the first to use this (revenue
        # rank, clause-code reason, translated text, etc.), but it's a plain
        # JSONB bag any future source_type can use the same way rather than
        # adding narrow columns per field.
        conn.execute("""
            ALTER TABLE agent_classifications
                ADD COLUMN IF NOT EXISTS metadata JSONB
        """)
        # form_type/item_codes/filing_filed_at were sec_filing-only typed
        # columns, added before metadata existed - now redundant with it,
        # same JSONB-bag rationale as company_rank/company_percentile above.
        # insert_filing_classification() writes these into metadata instead.
        conn.execute("""
            ALTER TABLE agent_classifications
                DROP COLUMN IF EXISTS form_type,
                DROP COLUMN IF EXISTS item_codes,
                DROP COLUMN IF EXISTS filing_filed_at
        """)
        # signal_score was NOT NULL for every source_type, on the assumption
        # every classification produces a confidence value. GDELT's Stage B
        # relevance check (taiwan_market_signal, source_category=gdelt) is a
        # forced one-word HIGH/WEAK call that never elicits a real confidence
        # number - NULL says "not measured" instead of a fabricated constant.
        # Other source_types keep writing a real score; this only widens what
        # the column allows.
        conn.execute("""
            ALTER TABLE agent_classifications
                ALTER COLUMN signal_score DROP NOT NULL
        """)
        # agent_classifications has no unique constraint at all today, so
        # every insert_*_classification function's "ON CONFLICT DO NOTHING"
        # has nothing to conflict against - confirmed live that re-inserting
        # the same row creates a duplicate rather than a no-op. That's a
        # pre-existing gap across all source types; fixing it here only for
        # taiwan_market_signal (source_id is a real natural key for this
        # source - ticker+period for revenue, ticker+timestamp for material
        # announcements - unlike the other source types, which don't
        # consistently populate source_id). A partial index scopes this fix
        # to taiwan_market_signal only, leaving news/sec_filing/geopolitical
        # untouched rather than risking their existing behavior.
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_agent_classifications_taiwan_source_id
                ON agent_classifications (source_type, source_id)
                WHERE source_type = 'taiwan_market_signal'
        """)
