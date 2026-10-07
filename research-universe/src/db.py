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
        # Non-US market profile                                               #
        #                                                                      #
        # Every column below is country-NEUTRAL by design. Japan is the first #
        # market loaded, but Taiwan and Korea follow and must reuse these     #
        # same columns rather than add their own - which is why none of them  #
        # is named for an exchange or a currency. The source tables these     #
        # replace made exactly that mistake three times over: the same idea   #
        # was called `code` in Japan and `ticker` in Taiwan/Korea, and the    #
        # local-language name was `native_name` in two of them and           #
        # `korean_name` in the third.                                         #
        # ------------------------------------------------------------------ #
        # These two shipped as local_code/local_name and are renamed in
        # place. `native_name` is the word every market's own pipeline
        # already used before this table existed, and reading it back as
        # something else cost a silent failure: the agent mapped
        # local_name -> native_name by hand, and when that mapping was
        # half-updated every row came back with a null name, the
        # universe looked empty, and the service fell back to its
        # built-in table with only a warning to show for it. One name
        # end to end removes the mapping that failed.
        #
        # ADD COLUMN IF NOT EXISTS below cannot do this: it would leave
        # the old column beside a new empty one. Guarded on the old
        # name so a fresh database, which never had it, skips straight
        # past.
        for _old, _new in (("local_code", "code"),
                           ("local_name", "native_name")):
            conn.execute(f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'universe_companies'
                                  AND column_name = '{_old}')
                       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                                        WHERE table_name = 'universe_companies'
                                          AND column_name = '{_new}')
                    THEN
                        ALTER TABLE universe_companies
                              RENAME COLUMN {_old} TO {_new};
                    END IF;
                END $$;
            """)
        # The partial unique index is named for the column it covers.
        conn.execute("ALTER INDEX IF EXISTS uq_companies_country_local_code "
                     "RENAME TO uq_companies_country_code")

        conn.execute("""
            ALTER TABLE universe_companies
            -- Identity ----------------------------------------------------
            -- The exchange's own code, UNSUFFIXED: '6857', not '6857.T'.
            -- `ticker` keeps the suffixed form the rest of this table uses;
            -- this is the key filings are published under, and the only one
            -- EDINET/TDnet/IRBANK will answer to. TEXT because Kioxia's code
            -- is '285A' - never cast it to an integer.
            ADD COLUMN IF NOT EXISTS code          TEXT,
            -- The company's name in its home language, full legal form.
            ADD COLUMN IF NOT EXISTS native_name          TEXT,
            -- Other written forms of THIS company, used to match it in
            -- local-language articles. Distinct from native_name: Resonac
            -- files as レゾナック・ホールディングス but the press writes
            -- レゾナック, and matching on the legal name alone found zero
            -- articles for Resonac and Renesas where the short form found
            -- 5 and 7.
            ADD COLUMN IF NOT EXISTS aliases             TEXT[] DEFAULT '{}',
            -- Forms that LOOK like this company but are not it. A Korean
            -- chaebol needs this: matching 'Samsung' otherwise picks up
            -- Samsung Life and Samsung C&T.
            ADD COLUMN IF NOT EXISTS exclude_terms       TEXT[] DEFAULT '{}',
            -- What to type into a general web search to find news about
            -- this company, where its name alone is not enough. Disco and
            -- Towa are ordinary English words, so each carries
            -- "<name> Corporation semiconductor"; the other seventeen
            -- Japanese companies need nothing and leave this NULL, which
            -- means "search the name". Stored per company because the
            -- ambiguity is a fact about the name, not about the source.
            ADD COLUMN IF NOT EXISTS search_query        TEXT,
            -- 'MM-DD'. Most Japanese issuers close 03-31, most Taiwanese
            -- and Korean ones 12-31 - which is exactly why it is stored
            -- per company rather than assumed per country.
            ADD COLUMN IF NOT EXISTS fiscal_year_end     TEXT,

            -- Valuation and standing --------------------------------------
            ADD COLUMN IF NOT EXISTS market_cap_usd_bn   NUMERIC,
            -- Paired: a bare local figure is meaningless without its
            -- currency, and a column named for one currency cannot hold
            -- the next country's.
            ADD COLUMN IF NOT EXISTS market_cap_local    NUMERIC,
            ADD COLUMN IF NOT EXISTS local_currency      TEXT,
            -- Also paired: the weight is comparable across countries only
            -- if the index it is measured against travels with it.
            ADD COLUMN IF NOT EXISTS index_name          TEXT,
            ADD COLUMN IF NOT EXISTS index_weight_pct    NUMERIC,
            ADD COLUMN IF NOT EXISTS home_market_rank    INTEGER,
            -- Sales booked inside the home country, as a share of total -
            -- a different question from where the company is listed.
            -- Advantest is Tokyo-listed with 2.2% of sales in Japan;
            -- Resonac has 43.4%. A domestic shock reaches the second far
            -- harder.
            ADD COLUMN IF NOT EXISTS domestic_sales_pct  NUMERIC,
            -- Dates domestic_sales_pct, which comes from the annual report
            -- and holds for a year. Deliberately NOT market_data_as_of:
            -- see below.
            ADD COLUMN IF NOT EXISTS financials_period   TEXT,

            -- WHAT market_data_as_of DATES, AND WHAT IT DOES NOT
            --   The market snapshot ONLY: market_cap_usd_bn,
            --   market_cap_local, index_weight_pct, home_market_rank.
            --   Those move daily - three companies in the first Japanese
            --   load ran stock splits on the very day their figures were
            --   taken, which is how a stored price goes quietly wrong.
            --
            --   It does NOT date domestic_sales_pct or fiscal_year_end.
            --   One date cannot honestly stamp both, because they go
            --   stale at completely different rates; financials_period
            --   dates the annual-report figure instead.
            ADD COLUMN IF NOT EXISTS market_data_as_of   DATE
        """)

        # The real identity of a non-US row. `company_name` is already
        # UNIQUE, but a name is editable and a loader keyed on one creates
        # a duplicate the first time someone fixes a spelling. Partial so
        # the ~1,400 existing rows, which have no code, are untouched.
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_companies_country_code
                ON universe_companies (country, code)
             WHERE code IS NOT NULL
        """)

        # ------------------------------------------------------------------ #
        # Disclosed customers and other counterparties                        #
        #                                                                      #
        # Stored flat, by name: a counterparty does NOT get its own           #
        # universe_companies row. Many of them could not have one - this set  #
        # includes an Italian railway, a US transit authority and a German    #
        # grid operator, none of which belong in an AI-economy catalogue and  #
        # none of which have the website and category every row here needs.   #
        # ------------------------------------------------------------------ #
        conn.execute("""
            CREATE TABLE IF NOT EXISTS universe_company_customers (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                company_id      UUID NOT NULL
                                REFERENCES universe_companies(id) ON DELETE CASCADE,

                customer_name   TEXT NOT NULL,
                -- The counterparty's own listing wherever it trades - NASDAQ,
                -- the TSE, Taiwan, Korea, Frankfurt. NOT a US-tradability
                -- marker. NULL means genuinely unlisted (Arm China, CXMT),
                -- private (Bosch), a subsidiary of a listed parent (Sony
                -- Semiconductor Solutions), delisted (Toshiba), or not a
                -- company at all ("US hyperscalers (unnamed)").
                customer_ticker TEXT,

                -- Written forms of the counterparty IN THE LANGUAGE OF THE
                -- SOURCES WE READ - not its names in its own home country.
                -- Nvidia is American but carries エヌビディア because
                -- Japanese filings write it that way, and Samsung carries
                -- the Japanese サムスン電子 rather than the Korean 삼성전자.
                -- So this array is keyed by SOURCE language, not by the
                -- counterparty's nationality: when Korean sources are added,
                -- the same Nvidia needs 엔비디아 alongside, not instead.
                aliases         TEXT[] NOT NULL DEFAULT '{}',

                relationship    TEXT NOT NULL CHECK (relationship IN (
                                    'customer', 'distributor', 'licensee',
                                    'investee', 'partner', 'user_base')),

                -- NULL means NOT DISCLOSED - never zero, and the two are
                -- never conflated. Japanese issuers must name a customer
                -- once it passes 10% of sales, so an absent figure is itself
                -- a filed fact: nobody reached the threshold, not that
                -- nobody looked. Thresholds differ by country, so do not
                -- read a NULL here as "under 10%" outside Japan.
                pct_of_sales    NUMERIC,
                -- Which report the percentage came from. Ibiden's AMD share
                -- was 11.0% in FY3/25 and fell below the threshold in
                -- FY3/26 - the period is what tells a reader the figure is
                -- not current.
                period          TEXT,

                UNIQUE (company_id, customer_name, relationship)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_company_customers_company
                ON universe_company_customers (company_id)
        """)
        # Answers "which tracked companies sell to X" without a scan.
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_company_customers_name
                ON universe_company_customers (lower(customer_name))
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
