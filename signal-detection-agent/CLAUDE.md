# signal-detection-agent

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

`signal-detection-agent` is a FastAPI service (port 8003) that classifies news articles as
**signal**, **weak_signal**, or **noise** using an LLM-driven pipeline. Unlike `signal-detection`
(which uses vector similarity + corpus centroids), this service sends each article's text directly
to an LLM and gets back a structured classification with a score, reason, materiality, category,
and named entities.

Articles are fetched from `news-retrieval`. The service can trigger a fresh run or reuse the
latest completed run (useful for testing). Classification results are stored locally; full article
content remains in news-retrieval.

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
signal-detection-agent/
├── Dockerfile
├── requirements.txt
├── requirements-test.txt
├── pyproject.toml
├── CLAUDE.md
├── STRUCTURE.md
├── prompts/
│   ├── ai_universe_signal_classifier_v1.txt
│   └── ai_universe_signal_classifier_v2_refine.txt
├── src/
│   ├── __main__.py
│   ├── app.py
│   ├── auth.py
│   ├── config.py
│   ├── db.py
│   ├── seed.py
│   ├── routes/
│   │   ├── health.py
│   │   ├── run.py
│   │   └── jobs.py
│   ├── controllers/
│   │   └── run.py
│   ├── models/
│   │   └── jobs.py
│   ├── pipeline/
│   │   ├── classifier.py
│   │   ├── category_candidates.py   (parked - not wired in v1)
│   │   ├── taiwan_signal_classifier.py   (taiwan_market_signal: rank/clause-lookup/translate/classify)
│   │   ├── japan_companies.py        (japan_market_signal: the one static company/customer table)
│   │   ├── japan_signal_classifier.py   (japan_market_signal: J1-J7 + WATCHING)
│   │   └── japan_signal_view.py      (japan_market_signal: row -> card shaping)
│   └── adapters/
│       ├── news_client.py
│       └── web_search.py
└── tests/
    ├── conftest.py
    ├── test_caching.py
    └── test_smoke.py
```

## Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM API key (OpenAI or OpenRouter) |
| `OPENAI_BASE_URL` | LLM base URL (default: `https://api.openai.com/v1`) |
| `SIGNAL_DETECTION_MODEL` / `OPENAI_MODEL` | Base pass model (default: `gpt-4.1`) |
| `SIGNAL_DETECTION_MODEL_V2` | Second pass model — falls back to `SIGNAL_DETECTION_MODEL` if unset |
| `NEWS_RETRIEVAL_URL` | news-retrieval base URL (default: `http://news-retrieval:8000`) |
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | Signal-detection Postgres DB connection |
| `PIPELINE_POLL_TIMEOUT_SECS` | Max seconds to wait for a news-retrieval run (default: 1800) |
| `WEB_SEARCH_PROVIDER` | Web search backend: `duckduckgo` (default), `tavily`, `brave` |
| `WEB_SEARCH_API_KEY` | API key for Tavily or Brave (not required for DuckDuckGo) |
| `CLASSIFY_CONCURRENCY` | Max concurrent article classifiers (default: 8) — shared by the `news` domain and geopolitical_signal Stage B/C |
| `TAIWAN_CLASSIFY_CONCURRENCY` | Max concurrent Taiwan translate/GDELT-relevance calls (default: 5) |
| `TAIWAN_SIGNAL_DOMAIN` | news-retrieval domain slug for the Taiwan pipeline (default: `taiwan_market_signal`) |

## Taiwan Signal Pipeline

`taiwan_market_signal` (TWSE/TPEx revenue + material announcements, plus GDELT Taiwan
coverage) is classified by a separate path from the AI-universe `POST /run` pipeline above
- see [STRUCTURE.md](STRUCTURE.md) for the full flow. Entry point: `python -m src
classify-taiwan-signals` (Click command in `__main__.py`), scheduled twice daily (14:00 UTC
post-Asia-close, 21:00 UTC pre-US-open, Mon-Fri) via the `signal_detection_agent_taiwan_signals`
CloudWatch rule in `infra/modules/ecs_cluster/services.tf`. news-retrieval fetches this domain
on its own independent 4-hourly schedule and stops at fetch/dedup; all ranking, clause-code
lookup, translation (`OPENAI_MODEL_V2`), and LLM classification (gdelt only) happen in
`pipeline/taiwan_signal_classifier.py`. Results persist to the same `agent_classifications`
table as the AI-universe pipeline, distinguished by `source_type = 'taiwan_market_signal'`,
with Taiwan-specific fields (rank, clause reason, translated text) in the `metadata JSONB`
column. Dedup across the two daily runs (and across news-retrieval's ~4-6 polls per day) is by
a deterministic `source_id` (ticker+period or ticker+timestamp), not article row id, enforced
by a partial unique index - a run never re-classifies or re-inserts something already done.

## Japan Signal Pipeline

Full technical reference: [JAPAN_SIGNALS.md](JAPAN_SIGNALS.md) - sources, thresholds and their
real-data derivation, habit tables, DB schema, API filters, schedules, known limitations, and
the operational runbook. The summary below is the orientation version.

`japan_market_signal` (IRBANK forecast revisions/buybacks/company reference, Kabutan/EDINET
filings, SEAJ industry billings, MONOist capex news) is classified by its own separate path,
`pipeline/japan_signal_classifier.py` - see that module's own docstring for the full design,
habit-computation rationale, and real-data findings per signal type (kept there, not
duplicated here, since it's the actual source of truth and changes as each signal type is
built/tuned). All 7 of the Japan Signals spec's signal types (J1-J7) are implemented and wired
into one entry point, `classify_japan_signal_batch()`. J7 (press) is the only one that makes a
real LLM call (spec Section 6.6/10.1) - the other six are pure arithmetic/lookup, per the
spec's own explicit design intent. Spec Section 10.3's WATCHING section (a tracked company's
real elapsed time since its last genuine revision vs. its own stored cadence) is a separate,
8th classifier, `classify_stale_revision_pattern` (`source_category = 'jp_watching'`) - NOT
wired into `classify_japan_signal_batch` (that entry point's own daily window is too narrow to
ever find a company's true last revision) but into `refresh_japan_habits` instead, which
already pools the full wide-history window this check needs.

All static company reference data lives in ONE module, `pipeline/japan_companies.py` -
`JAPAN_COMPANIES`, keyed by TSE code, with each company's native name, fiscal year end,
market weight (TSE Prime share, Japan rank, Japan sales share, market cap) and its
disclosed customers (name, ticker, `pct_of_sales`, filed `period`, aliases,
`relationship`). It replaced three overlapping modules (`japan_ticker_universe.py`,
`japan_company_profile.py`, `japan_read_through.py`) that each held part of the same facts
and disagreed in places. `JAPAN_TICKER_UNIVERSE` remains as a list view over the same
objects, so the two never drift. This table is the intended migration unit into
research-universe's DB, so anything added here must map to a column there.

The twice-daily trader summary was REMOVED (2026-10-02, explicit user instruction): the
cards carry the same facts, and the prose restated them at the cost of an LLM call per run.
`pipeline/japan_signal_summary.py`, `GET /japan-signals/summary`, the
`summarize-japan-signals` command and both of its CloudWatch schedules are gone. The four
formatting helpers it owned (`_age_hours`, `_format_pct`, `_format_jpy_millions`,
`signal_implication`) moved into `japan_signal_view.py`, which is their only caller now.

Two read-only routes exist for this domain (both under `routes/jobs.py`, both
`require_auth`): `GET /japan-signals/universe` (the static 19-company reference list, built
field-by-field from `JAPAN_COMPANIES` in memory - not `agent_classifications`), and
`GET /japan-signals/results` (paginated, filterable - `code`, `source_category`,
`signal_detection`, `published_from`/`published_to`; delegates to the same `list_all_results`
the generic `GET /results` uses, with `source_type` pinned to `japan_market_signal`, then
shapes each row through `japan_signal_view.to_jp_signal`). Neither route, nor any other
Japan Signals command, is triggerable over HTTP - `classify-japan-signals`/
`refresh-japan-habits` are CLI-only, same as every other non-`ai_news` domain in this
service (`pipeline/dispatch.py`'s own module docstring states this architecture explicitly:
only per-article domains route through `POST /run`).

Each shaped card carries `entities`: which of that company's own disclosed customers the
event's text actually names, matched against the English name, native Japanese name and
ticker aliases held in `JAPAN_COMPANIES`. Computed at classification time and stored in
`agent_classifications.entities_json` (plus `entity_names_normalized` for filtering), not
recomputed per request. An empty list is the common and correct answer - only 4 of 394 real
rows name a customer, because a forecast revision states figures and mentions nobody.

Entry points (Click commands in `__main__.py`, CloudWatch schedules in
`infra/modules/ecs_cluster/services.tf`), anchored to real TSE market hours
(09:00-15:00 JST, JST = UTC+9, no DST) rather than an arbitrary buffer: news-retrieval fetches
twice daily (23:00 UTC pre-open, 06:30 UTC post-close), `classify-japan-signals` runs once
after each fetch (00:00 UTC, 08:30 UTC - reads pre-computed habit/reference caches, never
recomputes them inline; always scoped to today's pooled runs only, even on its first-ever
invocation - never a full-history backfill, that is `refresh-japan-habits`'s own job).
`refresh-japan-habits` (05:00 UTC on the 25th of each month) is the only occasional job -
recomputes all three stored caches - `japan_company_habits`, `japan_progress_habits`,
`japan_company_reference` - from the FULL pooled history in one pass, and also runs the
WATCHING check against that same pool - see refresh_japan_habits's own docstring. news-retrieval
fetches this domain fetch/dedup-only, same boundary as Taiwan/Korea. Results persist to the
same `agent_classifications` table, `source_type = 'japan_market_signal'`, distinguished by
`metadata.source_category` per signal type (`jp_forecast`, `jp_industry`, `jp_capex`,
`jp_ownership`, `jp_buyback`, `jp_watching`, etc.).

## Classification Retention (Postgres)

`agent_classifications` has no built-in expiry - rows persist indefinitely by default,
same as news-retrieval's `articles` table. One `source_type` value has an explicit
weekly cleanup job; every other `source_type` is retained forever.

Manual run: `python -m src expire-classifications --source-type <type> --days <n>` -
deletes `agent_classifications` rows for one `source_type` published more than `--days`
days ago (default 30); rows with a NULL `published` date are never deleted (fail-open,
no reliable age to judge them by) - same rule news-retrieval's `expire-articles` uses.

| `source_type` | Domain classified | Retention | Schedule (CloudWatch) | Rationale |
|---|---|-----------|------------------------|-----------|
| `news` | `ai_news` (`NEWS_DOMAIN`) | 180 days | Sunday 07:30 UTC | Deliberately longer than news-retrieval's 30-day `ai_news` article retention - classification is allowed to outlive its source article |

This schedule runs 1 hour after its corresponding `news_retrieval_ai_news_expire_weekly`
job (06:30 UTC - see `news-retrieval/CLAUDE.md`), so a classification is only ever expired
after its source article has already been deleted in news-retrieval, never the other way
around - the longer window just means the classification survives on its own for a while
after its source article is gone, before its own expiry catches up. `sec_filing` and
`taiwan_market_signal` are intentionally excluded - neither is driven by a
news-retrieval article with an expiry (SEC filing metadata is a permanent record;
`taiwan_market_signal` has no source-side expiry today).

## Guidance

- Use the Jira board (project key `CON`) to track and reference cards
- `category_candidates.py` is parked - re-enable by passing `category_hints` into `classify_article()` if category errors appear in production

## Maintenance

- Do not modify the Jira Board, Guidance, or Maintenance sections unless explicitly asked
