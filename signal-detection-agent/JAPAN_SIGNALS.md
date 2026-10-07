# Japan Signals — Technical Reference

Implementation reference for the `japan_market_signal` pipeline: data sources, schemas,
classification rules, thresholds, and operational procedures.

**Related documents:** [CLAUDE.md](CLAUDE.md) for service orientation,
[STRUCTURE.md](STRUCTURE.md) for the layer map, [TECHNICAL.md](TECHNICAL.md) for the
AI-universe `POST /run` pipeline, which this domain does not use.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture & Data Flow](#2-architecture--data-flow)
3. [The Tracked Universe](#3-the-tracked-universe)
4. [Data Sources](#4-data-sources)
5. [Signal Types](#5-signal-types)
6. [Stored Caches](#6-stored-caches)
7. [Database Schema](#7-database-schema)
8. [Configuration](#8-configuration)
9. [Function Reference](#9-function-reference)
10. [API Endpoints](#10-api-endpoints)
11. [CLI Commands & Schedules](#11-cli-commands--schedules)
12. [Error Handling & Edge Cases](#12-error-handling--edge-cases)
13. [Performance Characteristics](#13-performance-characteristics)
14. [Constraints & Coverage Boundaries](#14-constraints--coverage-boundaries)
15. [Operational Runbook](#15-operational-runbook)

---

## 1. Overview

`japan_market_signal` tracks 19 Japanese AI-supply-chain companies — semiconductor equipment,
materials, and electronics — and classifies disclosure events as **signal**, **weak_signal**,
or **noise**.

The defining design property is that most rules compare a company against **its own history**
rather than a fixed threshold. A 15% forecast revision is unremarkable for a company whose
typical revision is 27%, and highly unusual for one whose typical revision is 4%. A fixed bar
cannot express that distinction; a per-company habit can.

| Property | Value |
|---|---|
| Domain slug | `japan_market_signal` |
| Tracked companies | 19, read from research-universe |
| Fetch source types | 12 |
| Signal types | 8 — J1, J1b, J2, J3, J4, J5, J6, J7, plus WATCHING |
| LLM usage | J7 relevance, field translation, COMPANY LEVEL summary synthesis |
| Deterministic types | J1–J6 — arithmetic and lookup only |
| Storage | `agent_classifications` plus 3 cache tables |
| HTTP surface | 2 read-only routes; all commands are CLI-only |

Five of the seven spec signal types are arithmetic or a lookup. A model is used only to judge
whether a news headline states a fact or an opinion, which is the spec's explicit design intent.

---

## 2. Architecture & Data Flow

### Service boundary

| | `news-retrieval` | `signal-detection-agent` |
|---|---|---|
| Responsibility | Fetch from external sources, store, de-duplicate | Read stored data, compute habits, classify |
| Contains signal rules? | No | Yes — the only place any rule lives |
| Independent schedule? | Yes | Yes |
| Shared with other markets? | Yes — Taiwan, Korea | Yes — same pattern, different rule sets |

Data flows one direction. A rule change requires no re-fetch; a fetcher failure does not affect
classification logic. This matches the boundary Taiwan and Korea use.

```
                    research-universe
                    ─────────────────
                    the 19 tracked companies + 112 disclosed customers
                              │
              ┌───────────────┴───────────────┐
              │ ?tracked=true                 │ &include_customers=true
              ▼                               ▼
news-retrieval                       signal-detection-agent
──────────────                       ──────────────────────
IRBANK     ┐                         ┌─ japan_company_habits
Kabutan    │                         ├─ japan_progress_habits     (caches, read once
EDINET     ├─→ articles ──(HTTP)──→  ├─ japan_company_reference    per batch)
SEAJ       │   (deduped by url)      │
MONOist    │                         ├─→ classify_japan_signal_batch()
Jiji       │                         │      ├─ J1  classify_forecast_revision
Newswitch  │                         │      ├─ J1b classify_margin_forecast_revision
DuckDuckGo ┘                         │      ├─ J2  classify_results_against_forecast
                                     │      ├─ J4  classify_industry_equipment_sales
                                     │      ├─ J5/J6 classify_capacity_and_ownership
                                     │      ├─ J7  classify_press          (LLM)
                                     │      └─ J3  classify_missing_revision
                                     │
                                     └─→ agent_classifications
                                            source_type = 'japan_market_signal'
```

research-universe supplies the company universe to both services and is read once per run on
each side (Section 3). It holds no signals and no classification state; a company is defined
there once for every market rather than once per service.

### Layering

`pipeline/japan_signal_classifier.py` performs no database access. Every cache it requires is
loaded by `controllers/run.py` and passed as an argument, matching the boundary every
`pipeline/*.py` module in this service follows. `pipeline/japan_signal_view.py` follows the
same rule, shaping cards from rows the controller reads.

### Classification run sequence

`run_japan_signal_classification(job_id, from_date, to_date)`:

1. `list_completed_runs(JAPAN_SIGNAL_DOMAIN, from_date, to_date)` — a window can span multiple
   completed news-retrieval runs, since that service polls on its own schedule
2. Pool articles across those runs, de-duplicating by `url` in memory
3. Load all three caches: `get_all_habits()`, `get_all_progress_habits()`,
   `get_all_company_reference()`
4. `classify_japan_signal_batch(...)`
5. `get_existing_japan_signal_source_ids(candidates)` — filter out already-classified items
6. Insert the remainder row by row, logging and continuing past individual failures
7. Mark the job completed with the inserted count

Caches are read from storage, never computed from the current window's articles. A daily run
compares each new revision against the company's full history rather than whatever falls inside
a one-day window.

---

## 3. The Tracked Universe

Every fetcher and classifier is scoped against one list of **19 companies**. Both services read
it from **research-universe**, which owns this data.

```
GET {RESEARCH_UNIVERSE_URL}/companies?country=Japan&tracked=true
GET {RESEARCH_UNIVERSE_URL}/companies?country=Japan&tracked=true&include_customers=true
```

news-retrieval makes the first call; this service makes the second, because its classifiers
also need each company's disclosed customers. Both resolve the universe **once per run** —
news-retrieval before any fetcher dispatches, this service on first access — so six Japan
fetchers in one run make one HTTP call between them, not six.

`tracked=true` is what narrows the catalogue to this pipeline's own universe, and it is not the
same question as country: research-universe holds 62 Japanese companies, of which 19 are
tracked. Filtering on country alone would have the fetchers pulling filings for Keyence and
Daikin.

### Fields

| Field | Type | Example | Notes |
|---|---|---|---|
| `code` | TEXT | `"6857"` | Text throughout — Kioxia's code is `"285A"`. The key filings are published under, and the only one EDINET/TDnet/IRBANK answer to |
| `company_name` | TEXT | `"Advantest"` | English name |
| `native_name` | TEXT | `"アドバンテスト"` | Full legal Japanese name |
| `aliases` | TEXT[] | `["レゾナック"]` | Other written forms — see below |
| `search_query` | TEXT | `"Disco Corporation semiconductor"` | What to type into an English web search. Set for 2 of 19 |
| `fiscal_year_end` | TEXT (MM-DD) | `"03-31"` | A recurring year-end, not a full date |
| `ticker` | TEXT | `"6857.T"` | Exchange-suffixed. The pipeline joins on `code`, not this |

Field names are the same on both sides — research-universe serves `code` and `native_name`,
and both pipelines read them under those names. They were briefly different, and the
translation layer that bridged them is what failed silently when it went stale; see
Availability below.

The API also carries a market profile — `market_cap_usd_bn`, `market_cap_local` with
`local_currency`, `index_name` with `index_weight_pct`, `home_market_rank`,
`domestic_sales_pct` with `financials_period`, and `market_data_as_of`. These are surfaced by
`GET /japan-signals/universe` (Section 10) and feed no classification rule.

`fiscal_year_end` is load-bearing: most tracked companies close on 31 March rather than
31 December, and every date and progress calculation reads it per company.

`market_data_as_of` dates the market snapshot alone. `domestic_sales_pct` comes from the annual
report and is dated by `financials_period` instead — one date cannot honestly stamp both,
because they go stale at completely different rates.

### Name matching

Japanese press routinely uses an abbreviated company name. Matching on the full legal name
alone finds **zero** articles for Resonac Holdings (レゾナック・ホールディングス) and Renesas
Electronics (ルネサスエレクトロニクス), where the abbreviated forms find 5 and 7 respectively
over the same sample.

Every name-matching function therefore checks `native_name` first, then **every** entry in
`aliases`. Five companies carry one today:

| Code | Company | Alias |
|---|---|---|
| 4063 | Shin-Etsu Chemical | 信越化学 |
| 7735 | SCREEN Holdings | SCREEN |
| 4186 | Tokyo Ohka Kogyo | 東京応化 |
| 4004 | Resonac Holdings | レゾナック |
| 6723 | Renesas Electronics | ルネサス |

`aliases` is a list rather than a single short-name field because Korea needs several forms per
company — a group prefix plus variants — and matching reads all of them rather than the first,
so array order never decides which form is tried.

### `search_query`

`press_jp_english_check` runs a general English web search per company. Two company names are
ordinary English words, and searching them bare returns unrelated results: **Disco** and
**Towa** each carry `"<name> Corporation semiconductor"`. The other seventeen search on their
own name.

### Availability

There is no local copy of the universe in either service. A failure to load raises
`UniverseUnavailable` and the run exits non-zero.

That is deliberate. A hardcoded table of the same 19 companies used to sit in
`pipeline/japan_companies.py` as a fallback, with a seeded `config.companies` doing the same
job in news-retrieval. Both were deleted, because by the time either was a fallback it had
already stopped being the same data: the database said Kioxia Holdings, Fujikura and Murata
Manufacturing where the table still said Kioxia, Fujikura Ltd and Murata. Falling back meant
serving names corrected months earlier, and saying nothing about it.

A Japan job is a one-off scheduled task. One that exits non-zero is noticed within the hour;
one that quietly classifies against stale companies is not noticed at all.

The loader also checks the response is **usable**, not merely present. A field rename once
returned HTTP 200 with every row intact and every name null — structurally fine, and empty
where it counted — so a response carrying no `company` or `native_name` on any row is
rejected rather than accepted as an empty universe.

### Approaches considered

**A static table in each service.** Unworkable, and removed. It puts the same company in
several places at once — a ticker universe in news-retrieval, a company profile and a
read-through table here — which lets them disagree, and names the same idea `code` in one and
`ticker` in another. A single owner means a company is defined once for every market rather
than once per service.

**Keeping the static table as a fallback.** Tried, and removed for the reason under
Availability above: a second copy of reference data drifts, and a fallback that serves drifted
data silently is worse than a run that fails.

**Country filter alone.** Rejected: returns 62 Japanese companies, only 19 of them tracked.

**A dedicated bulk endpoint.** Rejected: `GET /companies` already filters and paginates, so a
second route would duplicate that logic and leave two listings to keep in step. The tracked
filter and optional customer nesting were added to the existing endpoint instead.

**Customers nested by default.** Rejected: only this service's classifiers read them, and
every other caller of a ~1,470-row catalogue would pay for a join that no other row has data
for. `include_customers=true` is opt-in.

### Delisted company

Shinko Electric (6967) is delisted and is **not** in the universe. Filings already stored
against its code remain in `articles`; no fetcher pulls new data for it and no classifier
scopes against it.

---

## 4. Data Sources

Twelve source types feed this domain, all fetched by news-retrieval and stored in the shared
`articles` table.

| # | `source_type` | Provider | Frequency | Feeds |
|---|---|---|---|---|
| 1 | `irbank_financials` | IRBANK | daily | J1, J1b, J2, J3 |
| 2 | `irbank_buyback` | IRBANK | daily | J6 |
| 3 | `irbank_company_reference` | IRBANK | monthly | J5, J6 denominators |
| 4 | `kabutan_tdnet_mirror` | Kabutan | daily | Same-day disclosure coverage |
| 5 | `kabutan_buyback` | Kabutan | daily | Same-day buyback announcements |
| 6 | `edinet_filing` | EDINET | daily | J6 ownership |
| 7 | `edinet_buyback_status` | EDINET | daily | J6 corroboration |
| 8 | `edinet_extraordinary_report` | EDINET | daily | Extraordinary events |
| 9 | `seaj_billings` | SEAJ | monthly | J4 |
| 10 | `monoist_capex` | MONOist | daily | J5 |
| 11 | `press_jp` | Jiji Press, Newswitch | daily | J7 |
| 12 | `press_jp_english_check` | DuckDuckGo News | daily | J7 timing-gap context |

Authentication: EDINET requires a registered `EDINET_API_KEY`; a request without one returns
401. Every other source is free and requires no key.

---

### 4.1 `irbank_financials` — Forecast revisions and results

**Endpoints:** `irbank.net/{code}/tdnet` (list), `irbank.net/{code}/{doc_id}` (detail),
`f.irbank.net/pdf/{date}/{doc_id}.pdf` (filing PDF)
**Parser:** `pdfplumber`, with `tesseract-ocr` fallback
**Dedup URL:** `irbank-financials://{code}/{doc_id}`

The foundation of the habit-aware detection logic. Two HTTP round-trips per revision:

1. **List page** — the company's full disclosure history, filtered to 備考 (notes) blocks
   labelled 修正 (revision). Matching on this label rather than title text is required because
   real title wording varies; a variance-plus-forward-guidance notice lands in a 修正-labelled
   block regardless of its exact title.
2. **Detail page** — links to the source filing PDF, which is downloaded and parsed for the
   old/new figures and the company's stated reason.

The PDF is the source of record. IRBANK's HTML carries neither the old/new figures nor the
reason text.

#### Extracted fields

| Field | Extraction method |
|---|---|
| previous / revised figures | Table row matched by an `(A)`/`(B)` suffix on the row label. Filers use at least four literal spellings for "previous forecast" and "revised forecast", so this is a suffix pattern rather than an exact-string list |
| line-item label | The PDF's own header row, preserved untranslated |
| stated reason | Free text following a 理由 heading, terminated at the standard forward-looking-statement disclaimer |
| `_kind` | Computed at fetch time — see below |

#### The `_kind` tag

One document format covers both a forward-looking revision and a report of actual results
against an earlier forecast. `_kind` distinguishes them by checking whether the revised-figure
row's label contains 実績 (actual results):

- `"revision"` — J1's material
- `"actual_vs_forecast"` — J2's material

This tag determines which classifier touches each article and which rows contribute to a
company's habit. A company whose history consists entirely of actual-vs-forecast reports has a
habit sample size of zero, which is the correct reading of its filing record.

#### Stored row

```json
{
  "title": "Disco (6146) [2026-07-21]: 業績予想の修正に関するお知らせ",
  "url": "irbank-financials://6146/140120260721597097",
  "source": "IRBANK",
  "metadata": {
    "code": "6146",
    "company": "Disco",
    "figures": [
      {
        "売上高":   {"previous": 1400000.0, "revised": 1450000.0},
        "営業利益": {"previous": 285000.0,  "revised": 320000.0},
        "_kind": "revision"
      }
    ],
    "reason": "当社の精密加工装置等の機械製品については...",
    "pdf_url": "https://f.irbank.net/pdf/{date}/{doc_id}.pdf",
    "source_category": "jp_forecast",
    "doc_href": "/6146/140120260721597097"
  }
}
```

`figures` is a list because one filing PDF can carry multiple forecast tables — a filing mixing
a Q1 variance report with Q2 forward guidance produces two entries. Each Japanese line-item key
is preserved exactly as the filing labels it, with values in JPY millions. `_kind` is a
synthetic key added by the fetcher, so it cannot collide with a filing label.

#### Incremental behavior

Each candidate revision's synthetic URL is checked against already-stored URLs **before** the
PDF fetch and parse. The walk stops after 3 consecutive already-stored items, since the list is
newest-first. One code path serves both backfill and daily use: a company with nothing stored
receives a full backfill; subsequent runs are incremental.

`days_back` is applied as a client-side cutoff on each candidate's parsed date, since the list
page offers no server-side date-range parameter.

---

### 4.2 `irbank_buyback` — Buyback program history

**Endpoint:** `irbank.net/{code}/buyback`
**Dedup URL:** `irbank-buyback://{code}/{doc_id}`

The primary numeric source for buyback figures. The page holds a company's entire buyback
history organized by board-resolution program, with every required figure already structured in
HTML — no PDF fetch required.

Not scoped by `days_back`. The page is small — a handful of programs with a few entries each —
so the whole page is walked per run and de-duplication handles the overlap.

| Field | Example |
|---|---|
| `program_year` | `"2026"` |
| `program_resolution` | `"取締役会(2025年10月28日)での決議状況"` |
| `program_limits` | `"上限1800万株、1500億円"` |
| `program_period` | `"2025年11月4日～2026年10月28日"` |
| `share_change` | `"+45万株"` |
| `cumulative_amount` | `"1499億9671万"` |
| `cumulative_pct_of_limit` | `"100%"` |

This is a monthly running-status feed. Each entry is a progress update against an already
authorized program, not a fresh announcement.

---

### 4.3 `irbank_company_reference` — Total assets and shares outstanding

**Endpoints:** `irbank.net/{code}/bs` (balance sheet), `irbank.net/{code}` (main page)
**Dedup URL:** `irbank-company-reference://{code}/{period}`

Supplies the denominators for J5's percent-of-assets rule and J6's percent-of-shares rule.

The `/bs` page carries a structured historical table, one row per fiscal period, ordered
oldest-first; only the newest row is kept, since total assets moves at most once per fiscal
quarter and a multi-year history is unnecessary here.

Shares outstanding has no dedicated field on IRBANK and is derived as
`market capitalization ÷ previous closing share price` from the main company page. If the
derivation fails for a company, the total-assets half is still returned, so one malformed page
does not block the remaining reference fields.

```json
{
  "code": "6146",
  "company": "Disco",
  "fiscal_period": "2026/06",
  "total_assets_jpy_millions": 751159,
  "shares_outstanding": 108843600,
  "source_category": "jp_company_reference"
}
```

---

### 4.4 `kabutan_tdnet_mirror` and `kabutan_buyback` — Same-day disclosures

**Endpoint:** `kabutan.jp/disclosures/` — paginated (`?page=N`), with `?kubun=j` scoping to
buyback announcements (自社株取得)
**Dedup URL:** `kabutan-tdnet://{code}/{doc_id}` and `kabutan-buyback://{code}/{doc_id}`

One function serves both source types, dispatched by the `kubun` parameter.

The feed is walked page by page, newest-first. Each page is checked for its own date; once rows
roll over to the prior trading day, the walk stops — the fetch covers the current trading day
only. Every row is filtered client-side against the tracked universe.

The unfiltered feed spans roughly 30 pages for a full trading day; the `kubun=j` variant is far
smaller. A fixed page ceiling bounds the walk as a safety limit, and reaching it without a date
rollover logs a warning.

Daily-only by design, with no backfill: historical forecast and buyback records come from the
IRBANK sources, and this feed provides same-day coverage.

| Field | Example |
|---|---|
| `code` | `"6857"` |
| `company` | Company name as the row displays it |
| `market` | `"東証プライム"` |
| `category` | `"決算"` |
| `datetime` | Minute-precision timestamp |
| `pdf_url` | Link to the disclosure PDF |

---

### 4.5 `edinet_filing`, `edinet_buyback_status`, `edinet_extraordinary_report`

**Endpoints:** `api.edinet-fsa.go.jp/api/v2/documents.json` (list),
`api.edinet-fsa.go.jp/api/v2/documents/{doc_id}?type=5` (CSV export)
**Auth:** `EDINET_API_KEY` required
**Dedup URLs:** `edinet-filing://`, `edinet-buyback://`, `edinet-extraordinary://`, each
`{join_code}/{doc_id}`

One shared function handles all three document types, dispatched by a `mode` parameter.

#### Mode 1 — `shareholding` (docTypeCode 350)

The 5%-ownership rule filing. The join uses `issuerEdinetCode` (the company whose shares were
bought), which is distinct from `edinetCode` (the filer).

The holding percentage is not present in the list response. It requires a second call per
filing to the CSV export, reading the XBRL field
`jplvh_cor:HoldingRatioOfShareCertificatesEtc`. A filing can report this value more than once —
once per named holder, then as a filing-level total — so the last occurrence is taken, which is
the total.

```json
{
  "code": "3436",
  "filer_edinet_code": "E12444",
  "filer_name": "三井住友トラスト・アセットマネジメント株式会社",
  "doc_id": "S100Z2O2",
  "doc_type_code": "350",
  "issuer_edinet_code": "E02103",
  "holding_ratio": 0.0594,
  "source_category": "jp_ownership"
}
```

`holding_ratio` is a plain float fraction (`0.0594` = 5.94%), parsed from the CSV export.

#### Mode 2 — `buyback` (docTypeCode 220/230)

Share-repurchase status. The join uses `edinetCode` directly, since a company reporting its own
buyback is the issuer.

This document type has no discrete numeric field in either the list response or the CSV export.
Every figure sits inside one free-text XBRL block,
`jpcrp-sbr_cor:AcquisitionsByResolutionOfBoardOfDirectorsMeetingTextBlock`, as unstructured
Japanese prose. The text is stored exactly as returned, in `raw_acquisition_text`.

This source corroborates that a buyback filing exists on a given day. The numeric source of
record is `irbank_buyback`, which provides the same facts as discrete parsed fields.

#### Mode 3 — `extraordinary` (docTypeCode 180/190)

Extraordinary reports. `currentReportReason` — a legal-clause code identifying the event
category — is present directly in the list response, so no per-filing fetch is needed to
determine the category. Example: `"第19条第2項第2号の2"`, on a filing reporting a stock-option
issuance to directors and employees.

The numeric details behind a category still require the CSV/text-block fetch and are stored as
raw text, since this document type spans too wide a range of event types for one fixed field
set.

---

### 4.6 `seaj_billings` — Industry equipment billings

**Endpoints:** SEAJ's statistics index page (resolved fresh each run), plus the linked PDF
**Parser:** `pdfplumber`; the backfill path uses `xlrd`
**Dedup URL:** `seaj-billings://{month}-{qualifier}`

The index page is decoded as Shift-JIS. The current press release PDF link is resolved fresh
each run, since the filename is not stable across releases.

One release contains roughly 6 trailing months of data, and every row matching the expected line
format is extracted rather than only the newest.

| Field | Example |
|---|---|
| `period` | `"August 2026"` |
| `qualifier` | `"prelim"` or `"final"` |
| `billings_3mo_avg_millions_jpy` | `412000` |
| `mom_pct` | `3.2` |
| `yoy_pct` | `41.8` |
| `release_date` | `"2026-09-15"` |

`qualifier` is part of the dedup URL because SEAJ revises a month's figure after first
publishing it. The same calendar month legitimately appears twice — once `prelim`, later
`final` — and both versions are stored as distinct rows. The classifier resolves the preference
at classification time.

The stored figure is a **3-month moving average**, not a single-month billings number. No free
source publishes a true single-month figure for this market, and every downstream calculation
treats the value accordingly.

#### Backfill path

The live fetch returns only the current release's ~6 trailing months, short of the 12 months
J4's trailing baseline requires. A separate one-time backfill reads SEAJ's historical Excel
archive — a distinct link in legacy `.xls` format, parsed with `xlrd`, extending back to 2005.

`_SEAJ_BACKFILL_YEARS = 5` bounds the window, matching IRBANK's precedent and reflecting
semiconductor capex cyclicality. `_SEAJ_BACKFILL_SKIP_RECENT_MONTHS` keeps the backfill clear of
the live fetcher's active window, since the Excel archive carries no prelim/final qualifier of
its own.

---

### 4.7 `monoist_capex` — Capacity and investment news

**Endpoints:** `monoist.itmedia.co.jp/mn/series/1464/` (listing), plus each matched article page
**Dedup URL:** the article's own URL

MONOist's 工場ニュース (Factory News) series. The listing offers no per-company query, so the
whole listing is fetched and filtered client-side against `native_name` and `aliases`.

For each article surviving the company filter, the article's full page is fetched separately and
its body extracted — one extra request per matched article, not per listing row. A one-month
window typically matches 15–20 articles out of several hundred listing rows.

Both the listing and article pages are Shift-JIS encoded and decoded explicitly.

The body is fetched because the investment figure a J5 announcement needs appears in the
article's body prose rather than its listing blurb: a usable figure is present in the blurb for
about 20% of matched articles, versus about 62% in the full body.

Article pages can carry a trailing "related articles" block whose content the page-extraction
library does not always separate from the article text. Since J5 searches the body for the
largest yen figure, the extracted body is trimmed at the trailing-block marker before storage so
only the article's own content is retained.

---

### 4.8 `press_jp` — Japanese press coverage

**Endpoints:** `jiji.com/jc/list` (economy category), `newswitch.jp/keyword/detail/573`
(semiconductor topic)
**Dedup URL:** the article's own URL

Two sub-sources fetched independently and combined into one source type.

| | Jiji Press | Newswitch |
|---|---|---|
| Type | National wire service | Semiconductor/industry trade publication |
| Per-article date fetch | No — the listing carries the timestamp | Yes — the listing carries no date |

Neither listing offers a per-company query; each is fetched once and filtered client-side
against `native_name` and `aliases`.

Jiji's listing carries a date/time with no year (`"09/28 19:02"`); the current UTC year is
applied, since the listing is always current. Newswitch's listing carries no publish date, so
each matched article's page is fetched to recover it.

Both are stored with `body: NULL` — headline and timestamp only.

```json
{
  "title": "アドバンテスト (6857): {headline}",
  "url": "https://...",
  "source": "Jiji Press",
  "body": null,
  "metadata": {
    "code": "6857",
    "company": "Advantest",
    "source_category": "jp_press",
    "unconfirmed": true
  }
}
```

`unconfirmed: true` is set unconditionally by the fetcher for every article from both
sub-sources. Whether an item carries the unconfirmed label in a published result is decided by
the classifier, based on the publication.

---

### 4.9 `press_jp_english_check` — English coverage check

**Provider:** DuckDuckGo News (free)

For each tracked company, an English-language news search runs once, independently of any
Japanese article already found. This is not a translation of the Japanese sources; it answers
whether English coverage of the company currently exists, feeding J7's timing-gap context.

Recency is checked twice: once via the search tool's coarse time-window parameter, then via an
exact day-count cutoff applied client-side, since the tool offers only broad day/week/month/year
buckets.

---

### 4.10 De-duplication

De-duplication is enforced at the storage layer, uniformly across every source.

| Source type | Dedup key |
|---|---|
| `irbank_financials` | `irbank-financials://{code}/{doc_id}` |
| `irbank_buyback` | `irbank-buyback://{code}/{doc_id}` |
| `irbank_company_reference` | `irbank-company-reference://{code}/{period}` |
| `kabutan_tdnet_mirror` | `kabutan-tdnet://{code}/{doc_id}` |
| `kabutan_buyback` | `kabutan-buyback://{code}/{doc_id}` |
| `edinet_filing` | `edinet-filing://{filer_edinet_code}/{doc_id}` |
| `edinet_buyback_status` | `edinet-buyback://{edinet_code}/{doc_id}` |
| `edinet_extraordinary_report` | `edinet-extraordinary://{edinet_code}/{doc_id}` |
| `seaj_billings` | `seaj-billings://{month}-{qualifier}` |
| `monoist_capex`, `press_jp` | The article's own URL |

Each key is a stable synthetic identifier for a real-world record — never a database row id and
never a title.

The `articles` table carries a unique index directly on `url`, applied globally across every
domain and run, so a URL is stored once regardless of source type, company, fetch run, or code
path. This holds even when two different code paths attempt the same insert.

A second constraint allows one title only once per fetch run. Several sources reuse generic
title text across distinct records, so every affected source folds a value that is unique per
record into the stored title:

| Source | Title format |
|---|---|
| IRBANK financials | `{company} ({code}) [{date}]: {filing title}` |
| IRBANK buyback | `{company} ({code}) buyback status [{doc_id}]: {date}, {change}` |
| Kabutan | `{company} ({code}) [{datetime}]: {title}` |
| EDINET | `{filer} -> {code}: {docDescription}` with doc_id |

SEAJ's `prelim` and `final` rows for one calendar month are retained as distinct rows by design;
the classifier resolves the preference.

---

## 5. Signal Types

| Type | Function | `source_category` | Basis |
|---|---|---|---|
| J1 | `classify_forecast_revision` | `jp_forecast` | Per-company habit — median + MAD |
| J1b | `classify_margin_forecast_revision` | `jp_forecast` | Margin-gap habit |
| J2 | `classify_results_against_forecast` | `jp_forecast` | Per-company progress habit |
| J3 | `classify_missing_revision` | `jp_missing_revision` | Learned slot calendar |
| J4 | `classify_industry_equipment_sales` | `jp_industry` | 12-month trailing baseline |
| J5 | `classify_capacity_and_ownership` | `jp_capex` | % of total assets, co-occurrence |
| J6 | `classify_capacity_and_ownership` | `jp_buyback`, `jp_ownership` | % of shares outstanding |
| J7 | `classify_press` | `jp_press` | LLM fact-vs-opinion judgment |
| WATCHING | `classify_stale_revision_pattern` | `jp_watching` | Elapsed time vs. cadence |

J1 and J2 read the same `jp_forecast` articles but are mutually exclusive per article:
`figures[0]["_kind"]` routes each article to exactly one of them. J4, J5, J6 and J7 read disjoint
slices of the same pooled list, so passing the full list to each classifier is correct.

---

### 5.1 J1 — Forecast revisions

Classifies `jp_forecast` articles tagged `_kind == "revision"`.

#### Operating-profit line items

```python
_OPERATING_PROFIT_KEYS = ("営業利益", "営業利益（△損失）", "調整後営業利益")
```

| Key | Meaning | Filer |
|---|---|---|
| `営業利益` | Operating profit | Most companies |
| `営業利益（△損失）` | Operating profit (or loss) | Kioxia |
| `調整後営業利益` | Adjusted operating profit | Hitachi |

Hitachi reports adjusted operating profit as its official metric, with no standard 営業利益 key
in its primary table. All three keys are checked against a filing's first table, which is its
primary consolidated forecast table.

Renesas Electronics (6723) is excluded from J1 via
`_JAPAN_OPERATING_PROFIT_EXCLUDED_CODES` and handled by J1b.

#### Rules

| # | Rule | Outcome | Requires trusted habit |
|---|---|---|---|
| 1 | Reversal — raise after cut, or cut after raise, within one fiscal year | `signal` | No |
| 2 | Profit-to-loss or loss-to-profit swing | `signal` | No |
| 3 | Rare reviser (`revisions_per_year < 1.0`) files a revision | `signal` | Yes |
| 4 | Move exceeds 2× this company's typical size | `signal` | Yes |
| 5 | Currency- or accounting-only stated reason | `noise` | No |
| 6 | Move ≥ 20% and above this company's MAD-scaled bar | `signal` | Yes |

```python
_RARE_REVISER_THRESHOLD_PER_YEAR = 1.0
_TYPICAL_SIZE_MULTIPLE_THRESHOLD = 2.0
_ABSOLUTE_SIGNAL_THRESHOLD_PCT   = 20.0
_ABSOLUTE_SIGNAL_MAD_MULTIPLE    = 2.0
```

#### Rule 6's bar

Rule 6 requires a move to clear both an absolute floor and a company-relative bar:

```
move >= 20%  AND  move > typical_size_pct + (2 × typical_size_mad_pct)
```

Median absolute deviation scales the bar to each company's own spread. Typical revision sizes in
this sector span a wide range — Shinko Electric 37.8%, Screen Holdings 33.3%, Ibiden 33.2%,
Advantest 27.6% — so a company-relative bar is what distinguishes an unusual move from routine
activity for a volatile company. Under this bar Advantest fires on its 50–53% moves and not on
its routine ~27% ones.

A multiplier of 2 is the standard convention for a moderately unusual reading on a MAD-based
bar, comparable in spirit to roughly 2 robust standard deviations under a normal approximation.

```python
_ABSOLUTE_SIGNAL_TYPICAL_SIZE_MULTIPLE = 1.5
```

This applies as the fallback bar when a company's habit carries `typical_size_pct` but no
`typical_size_mad_pct`, which occurs when fewer than 2 computable percentage changes exist.

#### Trust gates

```python
_MIN_REVISIONS_FOR_TRUSTED_HABIT        = 3
_MIN_FISCAL_YEAR_SPAN_FOR_TRUSTED_HABIT = 3
```

A habit is trusted only when a company has at least 3 genuine revisions **and** those revisions
span at least 3 fiscal years.

Both gates are necessary because `revisions_per_year` divides by distinct fiscal years *with* a
revision, so a single isolated revision and a company revising once a year every year both
produce `1.0`. The span gate distinguishes them: Ibiden's 4 revisions across 4 consecutive
fiscal years is a reliable pattern, while a single revision alone in an otherwise empty window
is not.

Below the gates, only the habit-independent rules (reversal, profit/loss swing) and the absolute
≥20% rule can fire; everything else resolves to `weak_signal`.

---

### 5.2 J1b — Margin-based revisions

```python
_MARGIN_BASED_CODES                   = frozenset({"6723"})   # Renesas Electronics
_MARGIN_BASED_OPERATING_PROFIT_KEY    = "Non-GAAP営業利益率"
_MARGIN_GAP_SIGNAL_THRESHOLD_POINTS   = 10.0
_MIN_MARGIN_SAMPLES_FOR_TRUSTED_HABIT = 3
```

Renesas reports quarterly range-based guidance in Non-GAAP margin percentages — revenue,
gross-margin %, operating-margin % — with no absolute yen operating-profit figure. J1b measures
the gap between a new margin figure and the same filing's reference figure (prior-year actual
for the same period).

`compute_margin_revision_habit` returns only the fields this reporting style supports:

```python
{"typical_gap_pts": float | None, "sample_size": int, "is_trusted": bool}
```

`revisions_per_year`, `typical_direction` and `typical_months` are not computed here, since
those depend on comparing a revision against an immediately preceding revision in the same
fiscal year — a relationship that does not exist in this company's disclosures, whose only
comparable pair is new guidance against a fixed reference point.

---

### 5.3 J2 — Results against forecast

```python
_PROGRESS_SIGNAL_THRESHOLD_POINTS       = 15.0
_MIN_PROGRESS_SAMPLES_FOR_TRUSTED_HABIT = 3
```

Classifies `jp_forecast` articles tagged `_kind == "actual_vs_forecast"`, comparing progress
toward the full-year target against the company's typical progress at the same point.

Period type is detected by substring-matching the table's per-share net-income-style label:

| Marker | Period type | Progress candidate |
|---|---|---|
| `中間` | `half_year` | Yes |
| `四半期` | `quarter` | Yes |
| `当期` | `full_year` | No — the year is complete |

Substring matching is used rather than an exact key list because label wording varies across
filers.

The comparison baseline is keyed `(code, period_type)`, not code alone: a company's typical
progress at a half-year mark and at a quarter mark are different figures — Ibiden runs ~56% by a
typical quarter mark versus ~62% by its typical half-year mark.

Most company/period-type combinations currently hold 1–3 samples, below the trust gate, so the
habit-comparison rule applies to few combinations today and the `weak_signal` fallback is the
common outcome. The gate ensures no baseline is asserted from insufficient data.

---

### 5.4 J3 — Missing expected revision

```python
_MIN_YEARS_FOR_TRUSTED_SLOT_CALENDAR = 3
_SIGNAL_HIT_RATIO        = 0.8
_WEAK_HIT_RATIO          = 0.6
_SLOT_OVERDUE_GRACE_DAYS = 30
```

J3 detects an absence: a company that reliably announces in a given month has not done so.

It tracks the recurrence of **first-time forecast announcements** — `_kind == "revision"` with a
revised figure and no previous figure — rather than genuine revisions. The slot calendar is
learned from each company's real filing months via `_build_slot_calendar`, which groups
announcements by calendar month.

The hit ratio is computed against however many years of history exist for a given slot, rather
than a fixed denominator, since history depth varies per company. A slot is flagged only once it
is 30 days past its usual date, absorbing the normal year-to-year variation in filing dates —
Disco's October slot ranges from the 17th to the 29th.

#### Result shape

J3 results describe an absence, so there is no article to reference. Each result carries a
synthetic dict:

```python
"article": {
    "title": f"{company_name}: expected forecast announcement overdue",
    "published": as_of.isoformat(),
}
"source_id": f"japan-missing-revision://{code}/{as_of.year}-{month:02d}"
```

The real `as_of` timestamp makes J3 rows findable by date-windowed reads —
`list_all_results`' `published_from`/`published_to`, and therefore
`GET /japan-signals/results`. WATCHING uses the same pattern.

J3 results bypass the translate and metadata-refresh step in the batch entry point, which
applies only to results backed by a real article; J3's metadata and reason are already final and
in English.

#### Scope boundary

J3 detects a missing announcement slot, not company-wide silence. A company can go a long period
without a forecast revision while filing other disclosures continuously — Tokyo Electron and
Screen Holdings both show this pattern — so absence of a `jp_forecast` filing is not evidence
that a company has gone quiet. Determining that would require cross-referencing other disclosure
types, which is outside this classifier's scope.

---

### 5.5 J4 — Industry equipment sales

```python
_INDUSTRY_SIGNAL_SPREADS  = 2.0
_INDUSTRY_WEAK_SPREADS    = 1.0
_INDUSTRY_BASELINE_MONTHS = 12
```

J4 has no per-company concept; it judges one national monthly reading against its own recent
history.

1. Deduplicate stored months by `period`, preferring `final` over `prelim`
2. Sort chronologically
3. From the 13th month onward, compute against the trailing 12 months' `yoy_pct`:

```
average      = mean(trailing 12 months' yoy_pct)
spread       = stdev(trailing 12 months' yoy_pct)
spreads_away = (this month's yoy_pct − average) ÷ spread
```

A month with fewer than 12 predecessors produces no result, rather than being classified `noise`
or `weak_signal`.

| Outcome | Condition |
|---|---|
| `signal` | `abs(spreads_away) > 2.0` **or** `yoy_pct` is negative |
| `weak_signal` | `1.0 < abs(spreads_away) <= 2.0` |
| `noise` | `abs(spreads_away) <= 1.0` |

The negative-YoY condition treats a contracting industry reading as notable independent of its
statistical position, so a small negative reading close to the trailing average still qualifies.

This signal type uses mean and standard deviation, while J1 uses median and MAD, because the
inputs differ in kind: J4 reads a single continuous national time series with a long dense
history, where mean and standard deviation are appropriate, whereas J1 reads small, sparse,
fat-tailed per-company samples, where robust statistics are required.

---

### 5.6 J5 — Capacity and investment

```python
_CAPACITY_INVESTMENT_PCT_OF_ASSETS_THRESHOLD = 10.0
_CO_OCCURRENCE_WINDOW_DAYS                   = 14
_CAPEX_YEN_OKU_RE = re.compile(r"([\d,]+)億円")
```

1. Search title and body for a yen figure in the pattern `{number}億円` (hundred-millions of
   yen, the unit these announcements use). Where multiple figures appear, the largest is taken,
   since an announcement mentioning a prior investment for context states the new figure as the
   larger of the two.
2. Compute `investment ÷ total_assets × 100` from the company's stored reference data.
3. Check the same company's other classified signals in this batch — specifically genuine J1
   revisions — for any within 14 days in either direction.

| Outcome | Condition |
|---|---|
| `signal` | Investment ≥ 10% of total assets, **or** another signal from the same company within 14 days |
| `weak_signal` | Smaller investment with no co-occurring signal |
| `weak_signal` | Unmeasurable — no extractable yen figure, or no stored total-assets figure |

The two conditions cover different scales of event. Japanese industrial balance sheets are large
relative to a single plant or equipment announcement, so the asset-ratio condition addresses
exceptionally large commitments, while the co-occurrence condition captures announcements whose
significance comes from landing alongside a forecast revision. In current data the co-occurrence
condition is the one that promotes capacity announcements to `signal`; the largest single
announcement measured reaches 9.2% of assets.

---

### 5.7 J6 — Ownership and buybacks

```python
_OWNERSHIP_HOLDING_THRESHOLD_PCT = 5.0
_BUYBACK_PCT_OF_SHARES_THRESHOLD = 5.0
```

#### Buyback rule

The rule triggers on a buyback announcement, not on progress reports against a running program.
Since the source feed reports each program's progress repeatedly, the classifier treats the
first stored status entry for each distinct `program_resolution` as the announcement event and
every later entry as routine reporting.

`program_limits` (`"上限1800万株、1500億円"`) is parsed to extract the authorized share-count
ceiling separately from the yen amount:

```
program_limit_shares ÷ shares_outstanding × 100 >= 5%   →  signal
```

Below 5%, or with no stored `shares_outstanding` to compute against, the outcome is
`weak_signal`.

#### Ownership rule

EDINET docTypeCode 350, the large-shareholding report, is by law filed only once a holder's
stake has crossed 5%, and no equivalent filing exists below that threshold.

Every `jp_ownership` row is therefore classified `signal` unconditionally: the filing's
existence is the 5%-crossing event. The 100% signal rate for this category reflects the legal
filing trigger.

---

### 5.8 J7 — Press

The signal type that uses a relevance model call.

Three filters run before the model receives anything:

| Filter | Rule |
|---|---|
| Trusted publication | The article's domain must be Jiji or Newswitch |
| Company name in headline | The headline must name a tracked company |
| Already seen | Counts how many distinct publications carried the story |

The first two are structural guarantees under the current source set: only Jiji and Newswitch
are fetched, and the fetcher builds every title as `"{company} ({code}): {headline}"`, so
company-scoping is established at fetch time. The third evaluates to 1 for every article, since
cross-source duplicate matching covers other domains and not this one.

#### The prompt

Surviving candidates reach the model with exactly three fields — `company`, `source`,
`headline` — at `temperature: 0`.

```
You classify Japanese market headlines about semiconductor,
equipment, materials and electronics companies as HIGH or WEAK.

HIGH means the headline states a specific, checkable fact:
- a number (revenue, profit, orders, capacity, price)
- a change to a company forecast
- a named customer, partner, supplier or contract
- an order, a capacity change or an investment decision
- a government or regulatory action naming the company

WEAK means anything else:
- analyst opinion, ratings or price targets
- outlook or sentiment with no figure
- the company mentioned in passing in a market round-up
- a story mainly about a different company

Who is speaking matters. A fact stated by the company, the
exchange or a regulator is HIGH. The same fact predicted by an
analyst is WEAK.
```

The model judges only whether the headline states a checkable fact or reads as opinion. Habit,
progress, threshold checks and related signals belong to the deterministic signal types and are
not sent.

#### Publication handling

Both publications are first-tier for the classification rule. The unconfirmed label applies only
to Jiji, which as a national wire service reports developments ahead of formal company
confirmation. Newswitch's coverage reports completed technical achievements after the fact,
where no subsequent confirmation step exists.

| Outcome | Condition |
|---|---|
| `signal`, marked unconfirmed | Model answers `HIGH unconfirmed=true` and the source is Jiji |
| `signal` | Model answers `HIGH` |
| `weak_signal` | Model answers `WEAK` |
| `noise` | Removed by a filter before reaching the model |

The prompt text references Nikkei, which is the publication the spec describes; Jiji occupies
that role in this pipeline as the national wire service with a free access path.

This feed is thin in volume — a typical window yields a small number of matched articles across
both publications — consistent with the spec's characterization of this market as producing
"few but heavy" signals.

---

### 5.9 WATCHING — Stale revision pattern

```python
_STALE_SIGNAL_RATIO = 2.0
"source_id": f"japan-stale-revision://{code}/{as_of.date().isoformat()}"
```

Compares a company's elapsed time since its last genuine revision against its stored cadence. At
or above 2× the typical gap, the row is classified `weak_signal` — an observation, not a
confirmed event. The check applies to trusted habits only and makes no prediction.

The 2× bar accommodates normal variation: a company revising twice a year does not revise every
exactly-182 days, and a reliable cadence still varies year to year.

WATCHING runs inside `refresh_japan_habits` rather than `classify_japan_signal_batch`. It
requires each company's full revision history to establish a genuine last-revision date, which
the batch entry point's narrow daily window does not provide, and it runs on the occasional
cadence a stale-revision reading calls for.

Output format:

```
SoftBank Group (9984) last filed a forecast revision 2345 days ago;
typically revises about every 274 days (cuts about once a year).

Disco (6146) last filed a forecast revision 449 days ago;
typically revises about every 182 days (raises about twice a year).
```

---

## 6. Stored Caches

Three caches are read on every classification run and refreshed on their own schedule.

### 6.1 `japan_company_habits`

Computed by `compute_forecast_habit()` from genuine revisions only.

| Field | Formula | Rationale |
|---|---|---|
| `revisions_per_year` | count ÷ max(distinct fiscal years, 1) | Grouped by each company's own fiscal year — most tracked companies close on 31 March, so revisions in January and the following March fall in one fiscal year. The floor prevents a single-year sample from dividing by a fraction |
| `typical_size_pct` | `median(abs(% change))` | Median resists distortion from a single outsized revision |
| `typical_size_mad_pct` | median absolute deviation of those sizes | Scales rule 6's bar to the company's own spread; requires at least 2 computable changes |
| `typical_direction` | more frequent of raise/cut; ties resolve to raise | Descriptive text only; affects no numeric threshold |
| `typical_months` | 3 most frequent months; ties by earliest | A company can have multiple recurring windows per year |
| `sample_size` | count of genuine revisions | |
| `is_trusted` | `sample_size >= 3` and fiscal-year span `>= 3` | See §5.1 |
| `computed_from_years` | years of history used | |
| `refreshed_at` | timestamp | |

A revision where `previous == 0` has no computable percentage and is excluded from the size
calculation while still counting toward direction. A revision whose change is exactly zero is
excluded from both size and direction, counting as neither a raise nor a cut, since assigning it
a direction would affect reversal detection on the following revision.

### 6.2 `japan_progress_habits`

Keyed `(code, period_type)`. Kept as its own table rather than folded into
`japan_company_habits` because the natural key differs.

### 6.3 `japan_company_reference`

A cache of the latest values reported by `irbank_company_reference` — total assets, shares
outstanding, fiscal period — supplying J5 and J6's denominators.

### 6.4 Refresh semantics

`replace_habits()` performs a full delete-then-insert of the entire table rather than
per-company updates. This keeps the table internally consistent: a partial write would leave
some companies freshly computed and others stale, a distinction the classifier cannot detect
once stored.

`get_all_habits()` is called once per classification batch, loading every company's habit into
one in-memory `{code: habit_dict}` lookup, so each article resolves its habit without a query.
The three month columns are reassembled into a `typical_months` list, returning the same shape
`compute_forecast_habit()` produces.

`get_habits_refreshed_at()` returns the most recent `refreshed_at` across the table, reporting
habit age without reading every row.

---

## 7. Database Schema

Classification rows are written to the shared `agent_classifications` table with
`source_type = 'japan_market_signal'`, distinguished by `metadata.source_category`.
`japan_market_signal` is a permitted value in that table's `source_type` CHECK constraint.

### 7.1 Tables

```sql
CREATE TABLE japan_company_habits (
    code                  TEXT PRIMARY KEY,
    company               TEXT NOT NULL,
    revisions_per_year    NUMERIC,
    typical_size_pct      NUMERIC,
    typical_size_mad_pct  NUMERIC,
    typical_direction     TEXT,
    typical_month_1       SMALLINT,
    typical_month_2       SMALLINT,
    typical_month_3       SMALLINT,
    sample_size           INTEGER NOT NULL,
    is_trusted            BOOLEAN NOT NULL,
    computed_from_years   INTEGER NOT NULL,
    refreshed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE japan_progress_habits (
    code                  TEXT NOT NULL,
    period_type           TEXT NOT NULL,
    company               TEXT NOT NULL,
    typical_progress_pct  NUMERIC,
    sample_size           INTEGER NOT NULL,
    is_trusted            BOOLEAN NOT NULL,
    refreshed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (code, period_type)
);

CREATE TABLE japan_company_reference (
    code                      TEXT PRIMARY KEY,
    company                   TEXT NOT NULL,
    total_assets_jpy_millions NUMERIC,
    shares_outstanding        BIGINT,
    fiscal_period             TEXT,
    refreshed_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Recurring months are stored as three columns rather than an array, matching this codebase's
convention.

### 7.2 Indexes

```sql
CREATE UNIQUE INDEX idx_agent_classifications_japan_source_id
    ON agent_classifications (...)
    WHERE source_type = 'japan_market_signal';

CREATE INDEX idx_agent_classifications_japan_code
    ON agent_classifications (UPPER(metadata->>'code'))
    WHERE source_type = 'japan_market_signal';
```

Japan rows carry their company identifier in `metadata->>'code'`, not `metadata->>'ticker'`,
and a code can contain a letter (Kioxia's `285A`). `list_all_results` therefore exposes a `code`
parameter distinct from `ticker`, and this partial expression index serves it, parallel to the
`sec_filing` ticker index.

### 7.3 Classification `source_id` values

| Signal type | `source_id` |
|---|---|
| J1, J1b, J2, J4, J5, J6, J7 | The article's `url` |
| J3 | `japan-missing-revision://{code}/{year}-{month}` |
| WATCHING | `japan-stale-revision://{code}/{date}` |

J3 and WATCHING use synthetic keys because neither describes a specific article.

---

## 8. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `JAPAN_SIGNAL_DOMAIN` | `japan_market_signal` | news-retrieval domain slug |
| `JAPAN_SIGNAL_MODEL` | falls back to `SEC_FILING_MODEL` | Model for J7 relevance, field translation, and COMPANY LEVEL summary synthesis |
| `EDINET_API_KEY` | — | Required by news-retrieval for all three EDINET source types |
| `RESEARCH_UNIVERSE_URL` | — | research-universe base URL, e.g. `http://research-universe.staging.ocn.internal:8007`. **Required.** Unset or unreachable raises `UniverseUnavailable` and the run exits non-zero — there is no local copy (Section 3) |
| `RESEARCH_UNIVERSE_API_KEY` | — | Service key (`ru_` prefix). The companies listing is readable without it; the key is sent when present |

Both variables are set on this service and on news-retrieval, and both point at the internal
service-discovery address rather than the load balancer — the ALB serves research-universe
under a `/universe` path prefix that the internal address does not use.

`JAPAN_SIGNAL_MODEL` falls back to `SEC_FILING_MODEL`, this codebase's structured-extraction
tier, rather than the cheaper `OPENAI_MODEL_V2` tier used for forced one-word calls. The
requirement differs by task: a one-word classification that resolves incorrectly defaults safely
to `WEAK`, whereas a numeric value in a trader-facing summary or a translated field must be
accurate. The summary pipeline reinforces this by rendering INDUSTRY LEVEL and WATCHING directly
from stored data in code, sending only COMPANY LEVEL narrative synthesis to the model.

### Dependencies

This pipeline adds no Python dependencies to `signal-detection-agent`; all eight classifiers use
the standard library (`statistics`, `re`, `datetime`) plus the existing HTTP and database stack.

Fetch-side dependencies live in news-retrieval:

| Dependency | Used for |
|---|---|
| `pdfplumber` | IRBANK filing PDFs, SEAJ press releases |
| `xlrd` | SEAJ's legacy `.xls` historical archive |
| `tesseract-ocr` + Japanese language pack | OCR fallback for non-text-extractable PDFs |

---

## 9. Function Reference

### 9.1 Entry point — `pipeline/japan_signal_classifier.py`

```python
classify_japan_signal_batch(
    articles: list[dict],
    stored_habits: dict[str, dict] | None = None,
    stored_progress_habits: dict[tuple[str, str], dict] | None = None,
    as_of: datetime | None = None,
    stored_company_reference: dict[str, dict] | None = None,
) -> list[dict]
```

Runs every classifier against one pooled batch, returning one `{"article", "result"}` dict per
classified item — the same shape `classify_korea_signal_batch` and
`classify_taiwan_signal_batch` return.

Execution order carries one dependency: J2's results are collected before `classify_press`, so
the most recent `progress_pct` per company can supply J7's `progress_vs_usual` context line.
"Most recent" resolves by the latest published date among that company's J2 results in the
batch.

Results backed by a real article pass through `translate_japan_articles()` in one batched pass;
J3's results are appended afterward and bypass translation.

### 9.2 The tracked universe — `pipeline/japan_companies.py`

| Function | Returns |
|---|---|
| `japan_ticker_universe()` | Every tracked company |
| `company_for(code)` | One company, or `None` |
| `valuation_for(code, as_of=None)` | That company's market figures with `asOf` and `isStale` attached |
| `is_stale(as_of=None, code=None)` | Whether a company's market figures need a caveat |
| `mentioned_customers(code, text)` | Which of that company's disclosed customers `text` actually names, as `{name, type}` |
| `reset_universe_cache()` | Drops the fetched universe so the next read re-fetches. Tests only |

Every one of these raises `UniverseUnavailable` on first use if research-universe cannot be
reached, and no caller catches it. Each answers a question about which companies are tracked,
and there is nothing truthful to return when that is unknown.

These are functions, not module-level constants, because the universe is fetched at runtime: a
constant would be bound at import time in each consuming module, and a universe fetched
afterwards could never reach it. Nothing fetches at import — a module can be imported without
network access, and the first *call* is what loads. Later calls reuse the result for the life
of the process.

Tests inject a fixture universe directly into the cache (`tests/conftest.py`, autouse) rather
than reaching the service.

`mentioned_customers` matches against the company's own disclosed customer list rather than
extracting freely, so the candidate set is known and no model call is needed. That also bounds
the failure mode: a missed alias loses a link, where free extraction could invent one. Latin
aliases match on a word boundary — "ASE" sits inside "PHASE" — while Japanese forms match as
plain substrings, since Japanese has no word breaks. Customers with no ticker are skipped:
nothing a reader can look up means nothing actionable.

### 9.3 Habit computation

| Function | Returns |
|---|---|
| `compute_forecast_habit(revisions)` | One company's J1 habit |
| `compute_margin_revision_habit(revisions)` | One company's J1b margin-gap habit |
| `compute_progress_habit(actuals)` | One `(code, period_type)` progress habit |
| `compute_all_japan_habits(articles, computed_from_years)` | Every company's J1 habit from a pooled batch |
| `compute_all_japan_progress_habits(articles)` | Every `(code, period_type)` progress habit |

All are pure functions without database access.

### 9.4 Classifiers

| Function | Reads | Emits |
|---|---|---|
| `classify_forecast_revision(articles, stored_habits)` | `jp_forecast`, `_kind == "revision"` | J1 |
| `classify_margin_forecast_revision(articles, stored_habits)` | `jp_forecast`, margin-based codes | J1b |
| `classify_results_against_forecast(articles, stored_progress_habits)` | `jp_forecast`, `_kind == "actual_vs_forecast"` | J2 |
| `classify_missing_revision(articles, as_of)` | `jp_forecast` history | J3 |
| `classify_industry_equipment_sales(articles)` | `jp_industry` | J4 |
| `classify_capacity_and_ownership(articles, stored_company_reference)` | `jp_capex`, `jp_buyback`, `jp_ownership` | J5, J6 |
| `classify_press(articles, stored_habits, latest_progress_by_code)` | `jp_press` | J7 |
| `classify_stale_revision_pattern(articles, stored_habits)` | `jp_forecast` history | WATCHING |

### 9.5 Controller layer — `controllers/run.py`

| Function | Purpose |
|---|---|
| `run_japan_signal_classification(job_id, from_date, to_date)` | Pool runs, load caches, classify, dedup, insert |
| `refresh_japan_habits(from_date, to_date, computed_from_years)` | Recompute all three caches; run WATCHING |

### 9.6 Model layer

| Module | Table |
|---|---|
| `models/japan_company_habits.py` | `japan_company_habits` |
| `models/japan_progress_habits.py` | `japan_progress_habits` |
| `models/japan_company_reference.py` | `japan_company_reference` |
| `models/jobs.py` | `agent_classifications` — `list_all_results`, `insert_japan_signal_classification`, `get_existing_japan_signal_source_ids` |

---

## 10. API Endpoints

Two read-only routes in `routes/jobs.py`, both `require_auth`. Behind the API gateway they sit
under the `/agent/*` prefix.

### `GET /japan-signals/universe`

Returns the 19-company tracked list from the in-memory universe (Section 3), rather than from
`agent_classifications`, where the same 19 companies would repeat across every row.

Each entry is built field by field rather than spread from the record: spreading leaked the
market figures twice (once snake_case at the top level, again camelCase inside
`marketWeight`) and carried internal fields like `fiscal_year_end` along unasked. Building the
response explicitly also means the shape is fixed by this route, not by the universe's storage
format — the field names here are this service's own, and do not change with research-universe's.

| Field | Notes |
|---|---|
| `code`, `company`, `native_name` | Identity |
| `marketWeight` | `marketCapJpyTn`, `marketCapUsdBn`, `tsePrimePct`, `japanRank`, `japanSalesPct`, plus `asOf` and `isStale` so a consumer cannot show a months-old market cap as current. `asOf` is that company's own `market_data_as_of` |
| `customers[]` | `name`, `ticker`, `pct_of_sales`, `period`, `aliases`, `relationship`, `is_distributor`. Ordered by disclosed share, largest first, with undisclosed last |

`pct_of_sales: null` means the company does not disclose that customer at Japan's 10%
threshold — which is itself information, not a missing value. `relationship` defaults to
`customer` and is one of `customer`, `distributor`, `licensee`, `investee`, `user_base`,
`partner`.

### `GET /japan-signals/results`

Paginated, filterable classification rows. Delegates to the same `list_all_results` backing
`GET /results`, with `source_type` pinned to `config.JAPAN_SIGNAL_DOMAIN`.

| Parameter | Type | Notes |
|---|---|---|
| `limit` | int, 1–500 | Default 50 |
| `cursor` | str | Keyset pagination |
| `signal_detection` | str | `signal`, `weak_signal`, `noise` |
| `code` | str | TSE code, case-insensitive |
| `source_category` | str | `jp_forecast`, `jp_missing_revision`, `jp_industry`, `jp_capex`, `jp_buyback`, `jp_ownership`, `jp_press`, `jp_watching` |
| `published_from` | YYYY-MM-DD | Inclusive |
| `published_to` | YYYY-MM-DD | Inclusive |

```bash
curl -H "x-ocn-caller: $CALLER" \
  "$ALB/agent/japan-signals/results?code=6857&source_category=jp_forecast&limit=20"
```

Callers needing a filter this route does not expose can call `GET /results` directly with
`source_type=japan_market_signal`.

### HTTP trigger scope

`classify-japan-signals` and `refresh-japan-habits` are CLI-only,
matching every non-`ai_news` domain in this service: only per-article domains route through
`POST /run`.

---

## 11. CLI Commands & Schedules

Click commands live in `__main__.py`; CloudWatch rules in
`infra/modules/ecs_cluster/services.tf`.

Schedules are anchored to TSE market hours — 09:00–15:00 JST, JST = UTC+9, no DST. CloudWatch
cron expressions are UTC-only and carry no DST awareness.

| Job | Service | Cron (UTC) | Time |
|---|---|---|---|
| Fetch — pre-open | news-retrieval | `cron(0 23 * * ? *)` | 23:00 |
| Fetch — post-close | news-retrieval | `cron(30 6 * * ? *)` | 06:30 |
| `classify-japan-signals` | agent | `cron(0 0 * * ? *)` | 00:00 |
| `classify-japan-signals` | agent | `cron(30 8 * * ? *)` | 08:30 |
| `refresh-japan-habits` | agent | `cron(0 5 25 * ? *)` | 25th, 05:00 |
| SEAJ monthly fetch | news-retrieval | `cron(0 4 25 * ? *)` | 25th, 04:00 |

Each classify pass runs one hour after its corresponding fetch.

**All eight Japan rules are currently DISABLED** (verified live 2026-10-02) and are run by
hand as one-off ECS tasks. Re-enable only on an explicit instruction.

### Commands

```bash
python -m src classify-japan-signals [--from-date YYYY-MM-DD] [--to-date YYYY-MM-DD]
python -m src refresh-japan-habits [--from-date YYYY-MM-DD] [--to-date YYYY-MM-DD]
```

`classify-japan-signals` reads pre-computed caches and is scoped to the pooled runs in its
window, defaulting to a single day.

`refresh-japan-habits` recomputes all three caches from the full pooled history in one pass and
runs the WATCHING check against that pool. It defaults to `--from-date = today − 3650 days`
(10 years).

### One-time backfill

```bash
# IRBANK/Kabutan/EDINET history — matches refresh-japan-habits' 10-year window
python -m src trigger --domain japan_market_signal --days-back 3650
# news-retrieval's own docs cite 1825 (5 years) for this same flag: that is the
# minimum the spec requires for a usable habit, not a ceiling. 3650 is used here
# so the fetch window and the habit window below cover the same span.

# SEAJ history from the Excel archive (news-retrieval)
python -m src backfill-japan-seaj
```

`backfill-japan-seaj` is invoked deliberately and is not part of the scheduled `trigger` path.
The Excel archive carries no prelim/final qualifier, so its
`_SEAJ_BACKFILL_SKIP_RECENT_MONTHS` margin keeps it clear of the live fetcher's active window;
within that boundary it is safe to re-run, since article storage dedupes by URL.

### Rebuilding classified rows from scratch

`run_japan_signal_classification` skips any `source_id` already in
`agent_classifications` (`get_existing_japan_signal_source_ids`), and only `jp_watching`
rows upsert on conflict — every other category is `ON CONFLICT DO NOTHING`. So re-running
`classify-japan-signals` can never update an existing row. Backfilling a newly added
STORED column (as opposed to one `to_jp_signal` computes per request) means deleting the
rows first:

```sql
DELETE FROM agent_classifications WHERE source_type = 'japan_market_signal';
```

**Then run BOTH commands, not just the classifier** — they produce disjoint sets of rows:

```bash
python -m src classify-japan-signals --from-date <first run date> --to-date <today>
python -m src refresh-japan-habits    # jp_watching rows come from HERE
```

WATCHING is not part of `classify_japan_signal_batch` — its daily window is far too narrow
to find a company's true last revision — so a delete followed by only the classify command
silently drops every `jp_watching` row and leaves the watchlist empty. Verify the rebuild
by category, not by total count:

```sql
SELECT metadata->>'source_category', count(*) FROM agent_classifications
WHERE source_type = 'japan_market_signal' GROUP BY 1 ORDER BY 2 DESC;
```

---

## 12. Error Handling & Edge Cases

### Run-level failures

| Condition | Behavior |
|---|---|
| `NewsRetrievalError` while pooling articles | Job marked `failed`, logged with traceback, returns early |
| No articles in window | Job marked `completed` with `article_count=0` — not an error |
| Individual insert failure | Logged with its `source_id`; loop continues and the job completes with the real inserted count |

A single malformed row does not abort a classification run.

### Fetch atomicity

`run_pipeline()` in news-retrieval calls `create_articles(all_articles)` once, after the fetch
returns. A task terminated mid-fetch writes no rows, since the insert has not yet occurred, so a
stopped fetch requires no cleanup.

### Classification edge cases

| Case | Handling |
|---|---|
| Company below the trust gates | Only habit-independent rules fire; remainder resolves to `weak_signal` |
| J4 month with fewer than 12 predecessors | No result emitted |
| J5 with no extractable yen figure | `weak_signal`, marked unmeasurable |
| J5/J6 with no stored reference data | `weak_signal`; no ratio asserted |
| `previous == 0` in a revision | Excluded from size; direction counted |
| Exactly-zero percentage change | Excluded from both size and direction |
| Margin-reporting company in J1 | Excluded by code; routed to J1b |
| J3 and WATCHING rows | Synthetic article dict with real `published`; skip translation |

### Re-run safety

Every classification path is idempotent. `get_existing_japan_signal_source_ids` filters
already-classified items before insert, and a partial unique index enforces the same guarantee
at the database level, so a re-run neither re-classifies nor duplicates prior work.

---

## 13. Performance Characteristics

### Cache reads

`get_all_habits()`, `get_all_progress_habits()` and `get_all_company_reference()` are each called
once per classification run. With 19 companies these are small reads, and every per-article
lookup resolves against an in-memory dict.

### Incremental fetching

IRBANK's fetcher checks each candidate's synthetic URL against stored URLs before the PDF fetch
and parse, and stops after 3 consecutive already-stored items. Measured behavior for one
company:

| Scenario | Result |
|---|---|
| Nothing stored (backfill) | 19 revisions in 38.9s |
| Everything stored | 0 revisions in 0.3s |
| One new revision | 1 revision in 3.9s |

### LLM call volume

J7 issues one relevance call per headline surviving all three filters, a small number per run.
Translation runs as a single batched pass over results backed by real articles. The summary
issues one call, for COMPANY LEVEL.

### Fetch cost

A full 10-year backfill across all sources completes in approximately 1560s, yielding
approximately 900 articles.

---

## 14. Constraints & Coverage Boundaries

| Area | Constraint |
|---|---|
| Habit sample depth | A company whose filing history contains only actual-vs-forecast reports has a habit sample size of zero and no trusted habit |
| PDF page boundaries | A table split across pages is reassembled by pairing a header-only trailing table with a headerless leading table on the next page |
| Non-extractable PDFs | A small share of filings use a PDF font type with no character-identity map; these route to the `tesseract-ocr` fallback |
| Label variants | One line-item label appears under two spellings across filers; both are checked |
| Margin-based reporting | Renesas (6723) is served by J1b rather than J1 |
| Kabutan page ceiling | A high-volume results-season day can reach the page ceiling before the date rollover; the fetch logs a warning and covers the pages walked |
| J7 duplicate matching | The "already seen" count evaluates to 1, as cross-source duplicate matching does not cover this domain |
| J5 asset-ratio threshold | Balance-sheet scale means the co-occurrence condition, not the 10% condition, promotes capacity announcements in current data |
| J2 baseline depth | Most company/period-type pairs hold 1–3 samples, below the trust gate |
| SEAJ granularity | Figures are a 3-month moving average; no free source publishes true single-month data |
| J3 scope | Detects a missing announcement slot, not company-wide silence |
| MONOist trailing blocks | Article bodies are trimmed at the trailing-block marker before storage |

---

## 15. Operational Runbook

### Rollout sequence

| Step | Action | Result |
|---|---|---|
| 1 | `terraform apply` | 18 resources added — the schedules in §11 |
| 2 | IRBANK/Kabutan/EDINET fetch, `--days-back 3650` | 908 articles, `run_id=524` |
| 3 | `backfill-japan-seaj` | SEAJ history from the Excel archive |
| 4 | `refresh-japan-habits` | All three caches populated; WATCHING check run |

Step 2's window must match `refresh-japan-habits`' default of 3650 days, so habits are computed
from the full intended history.

### Verifying health

```bash
CALLER=$(printf '{"sub": 1, "role": "admin", "domains": []}' | base64)

curl -H "x-ocn-caller: $CALLER" "$ALB/agent/japan-signals/universe"
curl -H "x-ocn-caller: $CALLER" "$ALB/agent/japan-signals/results?limit=5"
```

`x-ocn-caller` is base64-encoded JSON: `{"sub": int, "role": str, "domains": [int]}`.

**Gateway auth tiers.** `/auth/*`, `/news/*` and `/agent/*` use `optional_auth`, permitting
public health checks. `/signal/*` uses `require_admin` and always requires a valid caller
header, so an unauthenticated response from `/signal/health` reflects that route's access
policy.

### Retention

`japan_market_signal` rows are retained indefinitely. Only `news` has a scheduled cleanup job;
Japan is excluded on the same basis as `sec_filing` and `taiwan_market_signal`, having no
source-side article expiry for a classification to trail.

Manual expiry is available:

```bash
python -m src expire-classifications --source-type japan_market_signal --days <n>
```

Rows with a NULL `published` date are never deleted, since no reliable age exists to judge them
by. J3 and WATCHING carry real `published` timestamps and are therefore subject to the same age
rules as every other row.

---

## Related Files

| Path | Contents |
|---|---|
| `src/pipeline/japan_signal_classifier.py` | All eight classifiers and habit computation |
| `src/pipeline/japan_companies.py` | Reads the 19-company universe from research-universe. No local copy |
| `src/pipeline/japan_signal_view.py` | Row -> card shaping for `GET /japan-signals/results` |
| `src/models/japan_company_habits.py` | J1 habit storage |
| `src/models/japan_progress_habits.py` | J2 habit storage |
| `src/models/japan_company_reference.py` | J5/J6 reference storage |
| `src/controllers/run.py` | Cache loading, orchestration, habit refresh, summary |
| `src/routes/jobs.py` | The three read-only routes |
| `src/db.py` | Table definitions and indexes |
| `src/config.py` | `JAPAN_SIGNAL_DOMAIN`, `JAPAN_SIGNAL_MODEL` |
| `news-retrieval/src/pipeline.py` | All 12 Japan fetchers |
| `news-retrieval/src/seed.py` | `JAPAN_TICKER_UNIVERSE`, domain and source registration |
| `infra/modules/ecs_cluster/services.tf` | CloudWatch schedules |
