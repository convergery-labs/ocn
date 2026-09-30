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
| `daily` | 00:30 UTC daily (CloudWatch) | Macro indicators once per run, not per ticker: `FEDERAL_FUNDS_RATE`, `CPI`, `TREASURY_YIELD`, `UNEMPLOYMENT`, `NONFARM_PAYROLL`, `REAL_GDP`, `RETAIL_SALES`, `DURABLES`, `TOP_GAINERS_LOSERS`; then per ticker: `OVERVIEW` (+ `ROC` and `MOM` momentum, merged into the same item), `EARNINGS`, `TIME_SERIES_DAILY_ADJUSTED` |
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
| `ocn-market-macro` | `indicator` | `recorded_at` | 90 days | daily |

### Market data HTTP endpoints (proxied via api-gateway at `/news/market/*`)

| Endpoint | Returns | 503 if |
|----------|---------|--------|
| `GET /market/quote/{ticker}` | price, change, change_percent, volume, previous_close | no data |
| `GET /market/overview/{ticker}` | market_cap, pe_ratio, 52w high/low, analyst_target, beta, sector, revenue_ttm, shares_outstanding, momentum_roc, momentum_mom, moving_avg_50day, moving_avg_200day, eps, forward_pe, price_to_book, ev_to_ebitda, profit_margin, operating_margin_ttm, return_on_equity_ttm, quarterly_earnings_growth_yoy, quarterly_revenue_growth_yoy, dividend_yield, dividend_per_share | no data |
| `GET /market/price-history/{ticker}` | last 10 days of adjusted_close | no data |
| `GET /market/earnings/{ticker}` | next_report_date, estimated_eps, last_surprise_pct | no data |
| `GET /market/indices` | SPY, QQQ, SOXX price + change_percent | no data |
| `GET /market/status` | current_status, local_open, local_close | no data |
| `GET /market/macro` | fed_funds_rate, cpi, treasury_yield_10y, unemployment, nonfarm_payroll, real_gdp, retail_sales, durables — each with date, value, unit; plus top_movers (top_gainers/top_losers/most_actively_traded lists) | no data |
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

## Taiwan Market Signal (`taiwan_market_signal` domain)

Fetch-and-store only - all ranking, clause-code classification, translation, and LLM
classification happen downstream in `signal-detection-agent` (see that service's CLAUDE.md),
not here. This domain's own `POST /run`/`trigger` fetch is the only responsibility owned by
news-retrieval; the boundary is deliberate (`src/pipeline.py`, near the end of the Taiwan
fetch path) so that no source type computes a signal or translates text inside this service.

Ticker universe: `TAIWAN_TICKER_UNIVERSE` in `src/seed.py` - a fixed list of `{ticker,
company, native_name, exchange}` (TWSE or TPEx), used to scope every Taiwan source below and
to set `metadata.translated_company_name` directly from known-correct English names (LLM
translation of bare 2-4 character Taiwan company names was confirmed live to produce serious
errors, e.g. 2383 Elite Material mistranslated as "Taiwan Semiconductor Manufacturing
Company" - so this field is never LLM-translated).

| Source | `source_type` | `source_category` (metadata) | What it fetches |
|--------|---------------|-------------------------------|------------------|
| TWSE Monthly Revenue | `twse_revenue` | `mops_revenue` | TWSE OpenAPI monthly revenue (`t187ap05_L`), full-dump filtered to TWSE tickers in the universe, with MoM/YoY deltas |
| TPEx Monthly Revenue | `tpex_revenue` | `mops_revenue` | TPEx OpenAPI monthly revenue (`mopsfin_t187ap05_O`), same shape for TPEx/OTC tickers |
| TWSE Material Announcements | `twse_material` | `mops_material` | TWSE OpenAPI material announcements (`t187ap04_L`, 重大訊息) |
| TPEx Material Announcements | `tpex_material` | `mops_material` | TPEx OpenAPI material announcements (`mopsfin_t187ap04_O`) - different keyset than TWSE's, normalized to a common shape in the fetcher |
| GDELT DOC API (Taiwan) | `gdelt` | `gdelt` | Taiwan-language financial press via GDELT DOC 2.0, scoped `sourcelang:chinese sourcecountry:TW`, queried per ticker by native Chinese name (when ≥3 chars - GDELT rejects shorter query keywords) and English company name |

Both TWSE/TPEx OpenData endpoints are full-dump, keyless JSON with no ticker/date query
param - the fetcher pulls the entire dataset each poll and filters to
`TAIWAN_TICKER_UNIVERSE`, and there is no backfill: missing a poll window loses that day's
new rows permanently, so the poll schedule (below) is the only capture mechanism.

GDELT's own API response (`mode=artlist`) has no body/snippet field, but this domain's GDELT
fetch does not rely on that - it separately fetches each surviving article's real webpage via
Trafilatura and sets `article["body"]` from the extracted page text, same as
`geopolitical_news`'s GDELT path.

**Schedule:** `${env}-news-retrieval-taiwan-market-signal` CloudWatch rule, every 4 hours
bounded to 01:00-16:00 UTC (fires 01/05/09/13 UTC), Mon-Fri only. The window covers TWSE/TPEx's
9:00 AM-1:30 PM Taipei trading session (01:00-05:30 UTC) *and* extends through 16:00 UTC
because 重大訊息 material-announcement disclosures are confirmed to cluster after market
close through the evening (17:30 Taipei / 09:30 UTC onward), not during trading hours. Does
not account for Taiwan's own holiday calendar (e.g. Lunar New Year) - polling a closed market
day is harmless (dedup prevents duplicate inserts) but not currently suppressed.

Downstream: `signal-detection-agent`'s `classify-taiwan-signals` CLI command runs twice daily
(14:00 UTC post-Asia-close, 21:00 UTC pre-US-open, Mon-Fri) and pools **all** of a day's
completed runs for this domain via `GET /runs?domain=taiwan_market_signal&status=completed`
(news-retrieval's own poll cadence above can produce several completed runs per day - the
consumer must read across all of them, not just the latest, or it silently misses earlier
runs' data).

## Japan Market Signal (`japan_market_signal` domain)

Fetch-and-store only, same boundary as Taiwan above - no ranking, translation, or LLM
classification happens in this service. Modeled directly on `taiwan_market_signal`'s
fetch/classify split; downstream classification is a `signal-detection-agent` task, not yet
built as of this writing.

Ticker universe: `JAPAN_TICKER_UNIVERSE` in `src/seed.py` - 20 companies from narrow,
near-monopoly steps in chipmaking (wafers, patterning chemicals, mask inspection, wafer
dicing/test, substrates) plus wider AI-universe read-through names. `code` is `TEXT`
throughout (Kioxia's code, `285A`, contains a letter - confirmed this matters the same way
Taiwan's ticker-as-text convention does). `fiscal_year_end` (`MM-DD`) is stored per company
for future progress-vs-forecast math - most companies here end their fiscal year 03-31, not
12-31. **Shinko Electric (6967) confirmed delisted** 2026-09-28 via EDINET's own official
code list (see `edinet_code.py` below) - its own entry shows "非上場" (unlisted) with a blank
securities-code field, resolving the spec's earlier "take-private status unconfirmed" flag.
Kept in the universe (its EDINET code still resolves for any residual filings) but no
ticker-keyed fetcher will ever match it going forward.

**Sourcing decisions (confirmed live before building), see git history on this file's
`japan_market_signal` section for the full record:**
- **TDnet** (Tokyo Stock Exchange's own disclosure network) has no free API - official tiers
  start ~JPY 50,000/mo, and even those carry a documented lag during earnings season. Not
  used. **IRBANK** (irbank.net, free, unofficial) substitutes for it entirely below.
- **J-Quants** (JPX's official API) free tier caps history at 2 years with a 12-week delay,
  and even a paid tier's revision data has no reason/commentary field - a further paid add-on
  would be needed for that. Not used - IRBANK substitutes for both gaps at no cost, and
  additionally exposes the source PDF filing directly (see below), which J-Quants never would
  have.
- **EDINET** (Financial Services Agency's official filing API) - confirmed working, free,
  requires a registered API subscription key (`EDINET_API_KEY`) but no approval delay.

All 9 originally-planned source_types are built and confirmed working together end-to-end (a
combined `trigger --domain japan_market_signal --days-back 31` run produced 459 real articles
across all of them with zero conflicts). A 10th, `irbank_company_reference`, was added
afterward to support signal-detection-agent's J5/J6 classifiers (see below):

| Source | `source_type` | `source_category` (metadata) | What it fetches |
|--------|---------------|-------------------------------|------------------|
| IRBANK Forecast Revisions | `irbank_financials` | `jp_forecast` | Earnings-forecast revision notices per company, via IRBANK's free `irbank.net/{code}/tdnet` disclosure-history mirror - see full extraction design below. Primary source for revision figures + reason text |
| IRBANK Buyback Status | `irbank_buyback` | `jp_buyback` | Buyback-program history per company via IRBANK's free `irbank.net/{code}/buyback` page - genuinely clean structured data (date, share-count change, cumulative amount, cumulative % of program limit), grouped by board-resolution program/year. Primary source for buyback figures |
| IRBANK Company Reference | `irbank_company_reference` | `jp_company_reference` | Latest known total-assets AND shares-outstanding figures per company, via IRBANK's free `irbank.net/{code}/bs` ("financial condition") page plus its main `/{code}` page - a clean per-fiscal-period history table for total assets, of which only the single newest row is kept per run, plus a derived shares-outstanding estimate (market cap / previous-close price - no direct share-count field exists anywhere on IRBANK). Reference data, not news - see full design below. Feeds J5's investment-vs-total-assets ratio and J6's buyback-vs-shares-outstanding ratio |
| Kabutan TDnet Mirror | `kabutan_tdnet_mirror` | `jp_disclosure` | Same-day disclosure mirror via Kabutan's free, global, paginated feed (`kabutan.jp/disclosures/`), walked page-by-page until the date rolls to the prior trading day, filtered client-side to the ticker universe. Daily-only, not backfilled |
| Kabutan Buyback | `kabutan_buyback` | `jp_buyback_announce` | Same feed as above, scoped server-side to `kubun=j` (自社株取得) - the buyback announcement TRIGGER, distinct from `irbank_buyback`'s ongoing status figures |
| EDINET Large Shareholding | `edinet_filing` | `jp_ownership` | 5%-large-shareholding filings (docTypeCode 350) via EDINET's official API - percentage held is fetched from each filing's own CSV export (never present in list metadata) |
| EDINET Buyback Status | `edinet_buyback_status` | `jp_buyback_status` | Share-repurchase status filings (docTypeCode 220/230) via the same EDINET API/infra as above (`_fetch_edinet_by_mode`) - stores the filing's raw acquisition text block as-is (no discrete numeric field exists for this doctype); same-day corroboration only, `irbank_buyback` is the numeric source of record |
| SEAJ Equipment Billings | `seaj_billings` | `jp_industry` | Monthly Japan semiconductor-equipment billings (3-month moving average - confirmed no free source anywhere publishes a true single-month figure) via SEAJ's free English press-release PDF, resolved fresh from the index page each run (the PDF's own filename is not stable/predictable) |
| MONOist Factory News | `monoist_capex` | `jp_capex` | Capacity/investment news via MONOist's free 工場ニュース series listing, filtered client-side by company `native_name` OR `short_name` when present (no per-company query capability exists for this source). Fetches each surviving article's own full body text too (`_fetch_monoist_article_body`, cp932-decoded then trafilatura-extracted) - added after confirming live that only ~20% of real articles carried an investment yen figure in the listing's own title/summary snippet vs. ~62% once the real article body is fetched; needed for J5's investment-figure extraction |
| Japan Press (Jiji + Newswitch) | `press_jp` | `jp_press` | Free Nikkei-equivalent wire coverage via Jiji Press's economy-category listing (broad) and newswitch.jp's semiconductor keyword page (targeted) - headline+timestamp only, no article body. Reuters Japan (anti-bot blocked) and Kyodo News English (no business/economy category exists) were checked and confirmed unusable |
| Japan Press English-Coverage Check | `press_jp_english_check` | `jp_english_coverage_check` | Independent per-company DuckDuckGo News search (free, no API key) - the design spec's own Step 5 English-mirror requirement. Same shape as Korea's `KOREA_GDELT_ENGLISH_SOURCE` (an independent per-company search, not a per-article cross-reference) - a distinct, earlier-in-the-pipeline use of the same tool signal-detection-agent's `web_search.py` already uses for classification-time entity context, not a duplication of that job |

### `irbank_company_reference` design (confirmed live against all 20 universe companies)

Added to support signal-detection-agent's J5 (capacity commitment) and J6 (ownership/capital
policy) classifiers, whose spec rules need "investment >= 10% of total assets" (J5) and
"buyback >= 5% of shares outstanding" (J6). Folded into one source_type since both facts come
from the same IRBANK domain in the same per-company loop and share the same slow refresh
cadence - see pipeline.py's own top-of-section comment for the full reasoning.

**Total assets**: `irbank.net/{code}/bs` carries a clean, already-structured
`財務履歴（百万円）` (financial history, JPY millions) table with one row per fiscal period
(confirmed live: 23 real quarterly/annual rows for Disco, back to 2007/03), oldest-first -
only the LAST row (newest fiscal period) is kept, since this is a slow-changing reference fact
(a company's total assets moves at most once per fiscal quarter), not something needing
habit-style history. Confirmed live 2026-09-29 for all 20 companies with 0 failures, including
Kioxia's letter-code (285A) and delisted Shinko Electric (6967, which still returns its last
known real figure, dated 2025/03 - consistent with its confirmed 2026-09-28 delisting noted
above). One real bug caught during testing: an initial version's table-caption regex assumed a
bare `<caption>財務履歴（百万円）</caption>` with nothing else inside, which broke on
Advantest's own page (whose caption carries an extra class attribute and a nested "see more"
`<ul>` before the caption closes) - fixed by loosening the regex to match up to `</caption>`
rather than immediately after the label text.

**Shares outstanding**: no direct share-count field exists anywhere on IRBANK's pages checked
(confirmed live: no 発行済株式/上場株式数 field on the main `/{code}` page or the `/dividend`
page) - derived instead as `market_cap / previous_close_price`, both of which ARE present on
the main `/{code}` page. Confirmed live three distinct real market-cap label formats exist
depending on company size (trillion+oku e.g. `24兆8880億`; oku+man only for smaller caps e.g.
`1660億2262万`; oku alone e.g. `1兆681億`) - all three handled by
`_parse_irbank_market_cap_yen`. Confirmed live for all 20 companies with 0 failures (e.g.
Advantest: market cap ¥24.888tn / price ¥33,060 -> ~752.8M shares, consistent with its real
public share count). Allowed to be independently `None` on a row without dropping the whole
row - total assets alone still serves J5 even if this derivation fails for one company.

Dedup: synthetic url `irbank-company-reference://{code}/{period}` (e.g.
`irbank-company-reference://6146/2026/06`) - `period` is the `/bs` page's own fiscal-period
label, so a company's reference row is only re-stored once its next real fiscal-period row
actually appears on IRBANK, not on every scheduled poll (shares-outstanding is tagged with the
same period even though it technically comes from a live market-cap snapshot - see
pipeline.py's own comment on why this is deliberate). Seeded `frequency_name: "monthly"` -
total assets changes at most quarterly, so a monthly check is already more frequent than
needed, and a day-level check would waste requests without gaining anything.

**`short_name` and the same stale-seed gotcha `GDELT_SOURCE` already has**: some
`JAPAN_TICKER_UNIVERSE` entries carry a `short_name` (e.g. Resonac Holdings's full
`レゾナック・ホールディングス` vs. the abbreviated `レゾナック` real press articles actually
use - confirmed live this is a REAL gap, not theoretical: Resonac and Renesas Electronics
each matched **zero** real MONOist articles by full `native_name` alone vs. 5 and 7
respectively once `short_name` was added). `monoist_capex` and `press_jp` both match against
either field via `_match_japan_company()` in `pipeline.py`. Same caveat as `GDELT_SOURCE`
above applies here too: `sources` rows are seeded `ON CONFLICT DO NOTHING`, so an
already-seeded database's stored `config` will NOT pick up a `short_name` added in code later
- confirmed live this silently kept an already-seeded test DB matching only 62 articles
instead of the corrected 74 until the stored `config` for both `monoist_capex` and `press_jp`
was updated directly (`UPDATE sources SET config = ... WHERE source_type = ...`). Any
environment seeded before this note was added needs the same manual update.

### `irbank_financials` extraction design (confirmed live against real filings)

Three-step fetch, no API key required (IRBANK has no auth), confirmed working end-to-end for
Advantest (6857, 19 real revisions back to 2013) and Disco (6146, 50 real revisions):

1. `GET irbank.net/{code}/tdnet` - IMPORTANT: this 301-redirects to `/{edinet_code}/tdnet`
   (e.g. `/6857/tdnet` → `/E01950/tdnet`); `httpx.get()` does not follow redirects by
   default, so every call against irbank.net passes `follow_redirects=True` (confirmed live
   this is not optional - a bare call raises on the 301 rather than erroring clearly). Parse
   the page's "備考" (notes) section - `<dd id="note_N">` blocks, each labelled (修正
   [revision], 説明 [presentation materials], 配当 [dividend], etc.). Keep only blocks
   labelled exactly "修正" - this is more robust than matching on title text directly, since
   real title wording varies (confirmed: a variance-vs-actual + forward-guidance combo notice
   still correctly lands in a 修正-labelled block despite not matching a simpler
   "...の修正に関するお知らせ" title pattern).
2. For each revision notice found, `GET irbank.net/{code}/{doc_id}` (the per-filing detail
   page) and extract its PDF link (`https://f.irbank.net/pdf/{date}/{doc_id}.pdf` - confirmed
   present on every detail page tested; an earlier design depended on an opportunistic
   `/news/{id}` IRBANK-generated HTML summary instead, confirmed via live testing across 4
   companies NOT to be reliably paired with every revision - dropped entirely in favor of the
   PDF, which also recovers the company's own reason text the HTML summary never had).
3. Download and parse the PDF with `pdfplumber` (`requirements.txt` dependency,
   `_extract_irbank_pdf_tables()`/`_fetch_irbank_filing_pdf()` in `pipeline.py`). Real filing
   PDFs are text-based (not scanned images) and contain a clean structured table: a header
   row of line-item names (売上高/営業利益/経常利益/当期利益 etc.), a row ending in some
   variant of "(A)" (previous forecast) and one ending in "(B)" (revised forecast or, for a
   variance-vs-actual notice, actual results) - matched by a permissive `(A)$`/`(B)$` suffix
   regex rather than an exact-string label allowlist, since real label prefixes vary more than
   expected (confirmed live 4 distinct variants across 2 companies: 前回発表予想(A)/
   今回発表予想(B), 前回発表予想(A)/今回修正予想(B), 前回発表予想(A)/今回実績(B), and
   前回予想/今回予想(B) - an earlier version of this matcher enumerated exact labels and
   silently produced zero tables for Advantest's newest filing as a result). **A single PDF
   can contain multiple such tables** (confirmed live: Disco's variance notice had 4 - Q1
   consolidated variance, Q1 standalone variance, Q2 consolidated forecast, Q2 standalone
   forecast - plus an unrelated dividend table that is naturally excluded since no
   previous/revised row matches it).

   The company's own stated reason for the revision - the one field the original design
   assumed no free source carried - **is available this way**: it's plain prose in the PDF's
   extracted full text (not the tables), following a "理由" or "修正の理由" heading, up to a
   reliable disclaimer boilerplate stop-marker ("※ 将来の事象..." or "（注）上記の予想は...").
   Stored as `metadata.reason` and in the article's `summary` field.

Dedup: synthetic url `irbank-financials://{code}/{doc_id}` - `doc_id` is globally unique per
IRBANK filing, so the existing global `uq_articles_url` index handles all dedup, same
convention as `dart-filing://`, `twse-revenue://`, etc.

**Incremental fetch / backfill** - `irbank_financials` is designed to run daily without
re-walking a company's entire history every time. IRBANK's `/{code}/tdnet` page has no
server-side date-range filter (confirmed live - it always returns the full history), so
`days_back` is applied as a client-side cutoff on each parsed disclosure's own date, combined
with a check against `get_already_stored_urls()` before any PDF is fetched - both act as
early-stops since the page is confirmed newest-first (walking stops once either the date
cutoff or `_IRBANK_STOP_AFTER_CONSECUTIVE_SEEN` consecutive already-stored items is reached).
One code path serves both a one-time backfill and every day after it - no separate mode or
flag:
- **One-time backfill** (do this once, before relying on any habit-aware classification
  downstream - the spec's own Section 9 Step 1 calls for 5 years of history):
  `trigger --domain japan_market_signal --days-back 1825`
- **Daily scheduled run** (once backfilled, this is fast - confirmed live ~0.2-1s per
  company when nothing new has happened, vs. ~30-40s per company on the initial backfill):
  `trigger --domain japan_market_signal --days-back 1`

**Trigger this domain** the same way as any other - no domain-specific route or CLI command
exists or is needed (`POST /run`/`trigger` are fully generic on `domain`, reading source
config from the DB):
```bash
# CLI (runs the pipeline in-process, exits when done)
python __main__.py trigger --domain japan_market_signal --days-back 1

# API (returns 202 immediately, runs as a FastAPI background task)
curl -X POST http://localhost:8000/run \
  -H "Authorization: Bearer <api-key>" -H "Content-Type: application/json" \
  -d '{"domain": "japan_market_signal", "days_back": 1}'
```

**No schedule wired yet** - unlike Taiwan/Korea, this domain has no CloudWatch rule yet. All 9
source_types are built and confirmed working together; what remains before scheduling this
like Taiwan/Korea: run the 5-year backfill manually first (`--days-back 1825`, see above -
only `irbank_financials` actually needs a multi-year window; every other source_type is
daily/monthly-scoped already), then add a daily CloudWatch rule with `--days-back 1`, modeled
on `news_retrieval_taiwan_market_signal`. `seaj_billings` is seeded with `frequency_name:
"monthly"` (`min_days_back` 30) - a daily `--days-back 1` trigger will correctly skip it most
days and only include it once `days_back` reaches 30, same gating every other domain's
sources already use (see `FREQUENCIES` in `seed.py`) - a monthly CloudWatch rule (or a
`--days-back 31` daily one) is needed for it to actually run periodically once scheduled.

### GDELT source scope: `geopolitical_news`

The `geopolitical_news` domain's GDELT source (`source_type = 'gdelt'`) queries are scoped with `sourcecountry:US` on every theme query (e.g. `theme:SANCTIONS sourcelang:english sourcecountry:US`) - used as a proxy for "does this event involve or affect the US," on the reasoning that a US-relevant event is highly likely to be covered by at least one US-domiciled outlet. Real tradeoff: this can miss US-relevant stories where foreign outlets (Reuters, BBC, Al Jazeera, etc.) cover an event before/instead of domestic US press. Source of truth for the query list: `GDELT_SOURCE` in `src/seed.py` - existing rows are `ON CONFLICT (url) DO NOTHING` on seed, so changing this list in code does **not** retroactively update an already-seeded database; an already-existing source row must be updated directly (SQL `UPDATE sources SET config = ...`) for the change to take effect.

## Guidance
- Read only the docs relevant to your task - not all of them
- Check the index above before asking for clarification; the answer is often in a doc
- When in doubt about scope or requirements, read the Functional Requirements or PRD first
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance
- Do not modify the Documentation Index, Jira Board, Guidance, or Maintenance sections unless explicitly asked
