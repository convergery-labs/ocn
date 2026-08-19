# news-retrieval

Part of the [ocn monorepo](../CLAUDE.md).

## How to use this file
Do not load all documentation upfront. Read the index below,
identify which docs are relevant to your current task, and
fetch only those. Use the 'Read when' column as your guide.

## Documentation Index
| Doc | Read when | Page ID |
|-----|-----------|---------|
| [Technical Specifications](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/30113793/Technical+Specifications) | Making architectural or technical decisions | 30113793 |
| ↳ [CON-95: API Integration-Readiness - Open Questions](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/61898754/CON-95+API+Integration-Readiness+Open+Questions) | Reviewing open questions for the API integration-readiness epic | 61898754 |
| [Sources](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/28705610/Sources) | Adding, removing, or evaluating data sources | 28705610 |
| [PRD](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/28705568/PRD) | Implementing or questioning any feature | 28705568 |
| [Roadmap](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/28508185/Roadmap) | Planning, scoping, or prioritising work | 28508185 |

Confluence space: `Projects` - Cloud: `opengrowthventures.atlassian.net`

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
news-retrieval/
├── Dockerfile
├── pyproject.toml        # pytest config (asyncio_mode=auto)
├── requirements-test.txt # test-only pip deps
├── README.md
├── CLAUDE.md
├── STRUCTURE.md
├── tests/                # automated test suite (pytest)
│   ├── conftest.py       # session/function fixtures (DB, keys, client)
│   ├── test_auth.py
│   ├── test_runs.py
│   ├── test_guard_chain.py
│   ├── test_cache_guard.py
│   ├── test_subset_guard.py
│   ├── test_pagination.py
│   ├── test_webhook.py
│   ├── test_ownership.py
│   └── test_pipeline.py
└── src/
    ├── __main__.py       # CLI entry point (uvicorn + click)
    ├── app.py            # FastAPI app factory
    ├── auth.py           # require_auth / require_admin FastAPI dependencies
    ├── pipeline.py       # Fetch + relevance filter pipeline (fetch → LLM title filter)
    ├── db.py             # Thin adapter: _new_connection() (POSTGRES_* env vars), init_db(), db_utils.configure(); re-exports get_db/transaction/DuplicateError from shared/src/db_utils.py
    ├── seed.py           # Idempotent seed for run_statuses, frequencies, domains, sources
    ├── models/           # DB query functions (repository layer)
    │   ├── api_key_domains.py
    │   ├── articles.py
    │   ├── atomic.py
    │   ├── domains.py
    │   ├── frequencies.py
    │   ├── runs.py
    │   └── sources.py
    ├── controllers/      # Business logic and multi-step orchestration
    │   ├── domains.py
    │   └── run.py
    ├── poller.py         # Background market data poller: AV fetch → DynamoDB; run_quotes (every 15 min) + run_daily (once daily); distributed lock via ocn-market-lock table
    └── routes/           # Thin HTTP adapters (FastAPI APIRouters)
        ├── grants.py
        ├── articles.py
        ├── domains.py
        ├── frequencies.py
        ├── health.py
        ├── market.py     # Market data read endpoints — 6 GET routes reading from DynamoDB, served at /market/*
        ├── run.py
        ├── runs.py
        └── sources.py
```

## Market Data

AV (Alpha Vantage) data is never fetched on the request path. A background poller writes to DynamoDB; the read endpoints serve from there.

### Poll modes

| Mode | Schedule | What it fetches |
|------|----------|----------------|
| `quotes` | Hourly, 14:00-20:00 UTC, Mon-Fri (CloudWatch) | `GLOBAL_QUOTE` per ticker, SPY/QQQ/SOXX indices, `MARKET_STATUS` |
| `daily` | 00:30 UTC daily (CloudWatch) | `OVERVIEW`, `EARNINGS`, `TIME_SERIES_DAILY_ADJUSTED` per ticker |
| `sec_filings` | 12:00 UTC daily (CloudWatch) | SEC EDGAR 8-K/10-Q/10-K metadata + filing link per ticker (see SEC Filings below) |

Run manually: `python __main__.py poll-market --mode quotes`

DynamoDB access for the poller is granted via an IAM role policy (`aws_iam_role_policy.news_retrieval_dynamodb_market` in `infra/modules/ecs_cluster/market_data.tf`) attached to `ecs_task_exec_ssm` (the same role used for ECS exec) - not the plain `ecs_task_execution` role. If `task_role_arn` on the news-retrieval task definition ever changes again, this policy attachment must move with it, or DynamoDB writes will start failing with an access-denied error that looks unrelated to the actual cause.

### DynamoDB tables (eu-north-1, PAY_PER_REQUEST, IAM auth)

| Table | Partition key | Sort key | TTL | Mode |
|-------|--------------|----------|-----|------|
| `ocn-market-quote` | `ticker` | `recorded_at` | 4 days | quotes |
| `ocn-market-indices` | `ticker` | `recorded_at` | 4 days | quotes |
| `ocn-market-status` | `market` | `recorded_at` | 4 days | quotes |
| `ocn-market-overview` | `ticker` | `recorded_at` | 30 days | daily |
| `ocn-market-price-history` | `ticker` | `date` | 1 year | daily |
| `ocn-market-earnings` | `ticker` | `recorded_at` | 30 days | daily |
| `ocn-market-lock` | `lock_key` | — | 20 min | both |
| `ocn-sec-filings` | `ticker` | `accession_number` | 180 days | sec_filings |

### Market data HTTP endpoints (proxied via api-gateway at `/news/market/*`)

| Endpoint | Returns | 503 if |
|----------|---------|--------|
| `GET /market/quote/{ticker}` | price, change, change_percent, volume, previous_close | no data |
| `GET /market/overview/{ticker}` | market_cap, pe_ratio, 52w high/low, analyst_target, beta, sector | no data |
| `GET /market/price-history/{ticker}` | last 10 days of adjusted_close | no data |
| `GET /market/earnings/{ticker}` | next_report_date, estimated_eps, last_surprise_pct | no data |
| `GET /market/indices` | SPY, QQQ, SOXX price + change_percent | no data |
| `GET /market/status` | current_status, local_open, local_close | no data |
| `GET /market/sec-filings/{ticker}` | recent 8-K/10-Q/10-K filings: form_type, filed_at, accession_number, primary_doc_url, cik, accepted_at, period_of_report, item_codes, filer_category | no data |

### SEC Filings

Fetched from SEC EDGAR (`data.sec.gov`), not Alpha Vantage. Ticker→CIK mapping via `https://www.sec.gov/files/company_tickers.json` (cached process-lifetime), filings list via `https://data.sec.gov/submissions/CIK{cik}.json`. Only 8-K, 10-Q, and 10-K form types are kept. Deduplicated per ticker by `accession_number` — each filing is a permanent, unique key from EDGAR, so re-running the poller never creates duplicates and skips filings already stored. Stores metadata + a link to the primary document only, not the filing body — `signal-detection-agent`'s daily filing-classification job reads this metadata via `GET /market/sec-filings/{ticker}` and fetches the body text itself (see `src/sec_edgar.py`).

### Ticker universe

Single source of truth: `get_tracked_ticker_universe()` in `src/pipeline.py`, which fetches US-listed tickers live from research-universe (`GET /companies?country=United States&has_ticker=true`, requires `RESEARCH_UNIVERSE_URL`/`RESEARCH_UNIVERSE_API_KEY`) and normalizes them to Alpha Vantage/SEC EDGAR format (`_normalize_av_ticker`: dot share-class suffixes like `BRK.B` → `BRK-B`; other dotted tickers, e.g. foreign exchange suffixes, are dropped). Returns `[]` (poll run skipped) if `RESEARCH_UNIVERSE_URL` is unset or research-universe is unreachable — there is no hardcoded fallback list. Used by both the Alpha Vantage fetch and the `GET /market/tracked-tickers` route, so they never drift apart.

This call crosses a security-group boundary: `research_universe`'s security group must allow ingress on port 8007 from `news_retrieval`'s security group (in addition to the ALB), or the request silently times out rather than erroring clearly — see `infra/modules/security_groups/main.tf`.

## Article Retention (Postgres)

Unlike the DynamoDB market-data tables (which all use native TTL), the Postgres `articles` table has no built-in expiry — rows persist indefinitely by default. Two domains have an explicit weekly cleanup job; every other domain's articles are retained forever.

Manual run: `python __main__.py expire-articles --domain <slug> --days <n>` - deletes articles for one domain published more than `--days` days ago (default 7); rows with a NULL `published` date are never deleted (fail-open, no reliable age to judge them by). One-shot, runs to completion and exits, same shape as `trigger` and `poll-market`.

| Domain | Retention | Schedule (CloudWatch) | Rationale |
|--------|-----------|------------------------|-----------|
| `geopolitical_news` | 7 days | Sunday 04:00 UTC | Short-lived event coverage; GDELT/SerpAPI volume is high and low-value past a week |
| `company_news` | 30 days | Sunday 05:00 UTC | Matches the TTL already used for Alpha Vantage's other data types (`ocn-market-overview`, `ocn-market-earnings`) |

Both schedules run after that domain's own daily fetch completes (`geopolitical_news` fetches at 02:00 UTC, `company_news` at 01:00 UTC) and are offset from each other, so no two scheduled jobs overlap. CloudWatch targets reference the task definition by family name only (no revision pinned), so a scheduled run always launches whatever revision is currently `ACTIVE` — see `infra/CLAUDE.md` for why revision-pinned targets are a real drift risk in this repo.

### GDELT source scope: `geopolitical_news`

The `geopolitical_news` domain's GDELT source (`source_type = 'gdelt'`) queries are scoped with `sourcecountry:US` on every theme query (e.g. `theme:SANCTIONS sourcelang:english sourcecountry:US`) - used as a proxy for "does this event involve or affect the US," on the reasoning that a US-relevant event is highly likely to be covered by at least one US-domiciled outlet. Real tradeoff: this can miss US-relevant stories where foreign outlets (Reuters, BBC, Al Jazeera, etc.) cover an event before/instead of domestic US press. Source of truth for the query list: `GDELT_SOURCE` in `src/seed.py` - existing rows are `ON CONFLICT (url) DO NOTHING` on seed, so changing this list in code does **not** retroactively update an already-seeded database; an already-existing source row must be updated directly (SQL `UPDATE sources SET config = ...`) for the change to take effect.

## Guidance
- Read only the docs relevant to your task - not all of them
- Check the index above before asking for clarification; the answer is often in a doc
- When in doubt about scope or requirements, read the Functional Requirements or PRD first
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance
- Do not modify the Documentation Index, Jira Board, Guidance, or Maintenance sections unless explicitly asked
