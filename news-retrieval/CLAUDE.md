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
| `quotes` | Every 15 min (CloudWatch) | `GLOBAL_QUOTE` per ticker, SPY/QQQ/SOXX indices, `MARKET_STATUS` |
| `daily` | 00:30 UTC daily (CloudWatch) | `OVERVIEW`, `EARNINGS`, `TIME_SERIES_DAILY_ADJUSTED` per ticker |

Run manually: `python __main__.py poll-market --mode quotes`

### DynamoDB tables (eu-north-1, PAY_PER_REQUEST, IAM auth)

| Table | Partition key | Sort key | TTL | Mode |
|-------|--------------|----------|-----|------|
| `ocn-market-quote` | `ticker` | `recorded_at` | 2 days | quotes |
| `ocn-market-indices` | `ticker` | `recorded_at` | 2 days | quotes |
| `ocn-market-status` | `market` | `recorded_at` | 2 days | quotes |
| `ocn-market-overview` | `ticker` | `recorded_at` | 30 days | daily |
| `ocn-market-price-history` | `ticker` | `date` | 1 year | daily |
| `ocn-market-earnings` | `ticker` | `recorded_at` | 30 days | daily |
| `ocn-market-lock` | `lock_key` | — | 20 min | both |

### Market data HTTP endpoints (proxied via api-gateway at `/news/market/*`)

| Endpoint | Returns | 503 if |
|----------|---------|--------|
| `GET /market/quote/{ticker}` | price, change, change_percent, volume, previous_close | no data |
| `GET /market/overview/{ticker}` | market_cap, pe_ratio, 52w high/low, analyst_target, beta, sector | no data |
| `GET /market/price-history/{ticker}` | last 10 days of adjusted_close | no data |
| `GET /market/earnings/{ticker}` | next_report_date, estimated_eps, last_surprise_pct | no data |
| `GET /market/indices` | SPY, QQQ, SOXX price + change_percent | no data |
| `GET /market/status` | current_status, local_open, local_close | no data |

### Ticker universe

Single source of truth: `_AV_BASE_TICKERS` in `src/pipeline.py` (453 tickers). Poller always uses this list — no separate env var.

## Guidance
- Read only the docs relevant to your task - not all of them
- Check the index above before asking for clarification; the answer is often in a doc
- When in doubt about scope or requirements, read the Functional Requirements or PRD first
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance
- Do not modify the Documentation Index, Jira Board, Guidance, or Maintenance sections unless explicitly asked
