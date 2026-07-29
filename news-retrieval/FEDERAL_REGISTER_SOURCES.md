# Federal Register Source — news-retrieval

Reference for the Federal Register REST API source added to the `geopolitical_news` domain.

## Summary

| | |
|---|---|
| **Domain** | `geopolitical_news` |
| **Source name** | Federal Register |
| **`source_type`** | `federal_register` |
| **Frequency** | `daily` (`min_days_back = 1`) |
| **API** | [federalregister.gov/reader-aids/developer-resources/rest-api](https://www.federalregister.gov/reader-aids/developer-resources/rest-api) |
| **Auth** | None required — free, public, no API key |

## Document types available

The API exposes exactly 4 document types (confirmed via live query against each):

| Type code | Name | Relevance to geopolitics |
|---|---|---|
| `PRESDOCU` | Presidential Document | Executive orders, proclamations, memoranda — highest signal, lowest volume |
| `RULE` | Rule | Final regulations (sanctions/export-control rule changes are high-signal; routine procedural rules are noise) |
| `PRORULE` | Proposed Rule | Draft regulations open for comment — early warning on upcoming policy |
| `NOTICE` | Notice | Broadest category — includes OFAC sanctions actions (high signal) alongside routine agency paperwork (noise) |

All 4 types are included in the seeded config.

---

# GDELT DOC 2.0 API — news-retrieval

Reference for the GDELT source added to the `geopolitical_news` domain.

## Summary

| | |
|---|---|
| **Domain** | `geopolitical_news` |
| **Source name** | GDELT DOC API |
| **`source_type`** | `gdelt` |
| **Frequency** | `daily` (`min_days_back = 1`) |
| **API** | [DOC 2.0 API](https://api.gdeltproject.org/api/v2/doc/doc) — [announcement](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) |
| **Auth** | None required — free, public, no API key |
| **Fetcher** | `_fetch_gdelt()` / `_fetch_one_gdelt()` in `src/pipeline.py` |

## Why DOC API, not Context 2.0

GDELT also has a Context 2.0 API that returns matched-sentence snippet text (useful for a summary), but live testing confirmed it **rejects bare `theme:` filters** ("keywords too short, too long or too common"). Only the DOC API accepts `theme:` filters, so DOC is used — trade-off is DOC returns no body/snippet text itself, so a separate Trafilatura fetch step gets the real body (see below).

## Body fetch

DOC API gives no body text, so after all queries are fetched and deduplicated, `_fetch_gdelt()` fetches each article's full body via Trafilatura in parallel (10 workers), same library/pattern already used for RSS and SerpAPI sources elsewhere in `pipeline.py`. Live-tested: 200/250 articles from a single theme query got real extracted body text; the rest returned `None` (paywalls, JS-rendered pages, or blocked fetches — normal Trafilatura behavior, not GDELT-specific). `summary` stays `None` — GDELT has no short-description field, and the RSS/NewsAPI convention keeps `summary` (short, source-provided) distinct from `body` (full extracted text).

**Cost control**: GDELT's theme queries return heavily overlapping results day-to-day, so before the body-fetch step, `_fetch_gdelt()` checks `get_already_stored_urls()` and drops any URL already stored — those articles skip the Trafilatura fetch entirely.

Dedup is **global**, not domain-scoped: `articles.url` has a DB-enforced unique index (`uq_articles_url`, `WHERE url IS NOT NULL`) — a URL is stored once, ever, regardless of which domain's run sees it first. `get_already_stored_urls()` is a bounded existence check (`WHERE url = ANY(candidate_urls)`, scoped to the current run's fetched URLs, not a full historical pull) used as a cheap pre-filter before expensive work (LLM relevance filtering, GDELT's body-fetch); the DB's unique index is the actual backstop that guarantees no duplicate is ever inserted, even if the pre-filter is skipped, buggy, or races with a concurrent run. Practical effect: if the same article URL matches sources in two different domains, whichever domain's run reaches it first stores it — the other domain will not see that URL again.

## Query design: single theme per query, not OR-joined

Each query filters on exactly **one** theme code (e.g. `theme:ARMEDCONFLICT sourcelang:english`), not multiple themes OR-joined together. Live testing confirmed single-theme queries work; the OR-joined form (`(theme:X OR theme:Y) sourcelang:english` — GDELT's own documented syntax) could not be verified due to persistent rate-limiting during testing, so it was avoided. Splitting into single-theme queries costs more requests per run (27 vs. 12) but each one is confirmed-working syntax.

English-only (`sourcelang:english` on every query) — non-English coverage was explicitly out of scope for this integration.

## Rate limiting

GDELT enforces an informal, undocumented rate limit — its own 429 response says "one every 5 seconds," but live testing showed it can stay in effect far longer (minutes) regardless of request cadence, likely tied to shared/pooled egress IPs.

`_fetch_gdelt()` runs queries **sequentially** (not parallel) with a 10-second minimum interval, in **round-robin passes** rather than retrying each query immediately on 429: pass 1 runs every query once, in order; any that come back 429'd are collected and retried together in pass 2, then pass 3, up to `_GDELT_MAX_ROUNDS` (3) total passes. A query still 429ing after the last pass is skipped for this run (fail-open per query, not per run). This is deliberately different from retrying one query repeatedly before moving to the next — that would stall every later query behind whichever one happens to be rate-limited first, when in practice more real time passing (by working through the other queries first) is what actually helps the limit clear.

Live-tested: confirmed the round-robin ordering is correct (a later query runs before an earlier rate-limited query is retried), and confirmed graceful fail-open when GDELT stays throttled for the entire run (3/4 queries in one live test never cleared across all 3 rounds — `_fetch_gdelt` returned the successful query's results and logged the rest as skipped, without crashing).

Separately, GDELT's DOC API has been observed to occasionally return `200 OK` with malformed JSON (an unescaped control character in article text breaking `resp.json()`). This is treated the same as any other per-query failure — logged, that query's results are dropped, the run continues — since retrying wouldn't help; the same malformed response would likely recur for that query on that data.

A full run of all 27 queries takes several minutes under normal conditions (longer if GDELT is throttling and round-robin passes are needed), plus additional time for the parallel body-fetch step across all deduplicated article URLs afterward.

## Theme filters seeded (27 queries)

| Category | Theme code(s) — one query each |
|---|---|
| Armed conflict | `ARMEDCONFLICT`, `MILITARY`, `CEASEFIRE` |
| Terrorism | `TERROR`, `WB_2467_TERRORISM` |
| Insurgency / rebellion | `REBELLION`, `REBELS`, `INSURGENCY`, `SEPARATISTS` |
| Sanctions / blockade | `SANCTIONS`, `BLOCKADE` |
| Civil unrest | `PROTEST`, `VIOLENT_UNREST` |
| Political violence | `KILL`, `ASSASSINATION` |
| War crimes / atrocities | `HUMAN_RIGHTS_ABUSES`, `WB_2509_GENOCIDE`, `WB_2510_WAR_CRIMES` |
| Displacement | `DISPLACED`, `REFUGEES` |
| Peace / diplomacy | `PEACEKEEPING`, `RELEASE_HOSTAGE` |
| Weapons proliferation | `WB_2503_WEAPONS_PROLIFERATION_AND_ARMS_CONTROL`, `WB_2505_WEAPONS_OF_MASS_DESTRUCTION` |
| Cyber | `CYBER_ATTACK` |
| Borders / military cooperation | `BORDER`, `MILITARY_COOPERATION` |

Full query strings live in `GDELT_SOURCE["config"]["queries"]` in `src/seed.py`.

## Fields returned (DOC API, `format=json`, `mode=artlist`)

| Field | Maps to | Notes |
|---|---|---|
| `url` | `articles.url` | |
| `title` | `articles.title` | |
| `domain` | `articles.source` | outlet's domain, e.g. `rawstory.com` |
| `seendate` | `articles.published` | GDELT's crawl/index time, **not** true publish time — no official SLA, ~4hr median lag observed for well-covered stories in third-party research |
| `sourcecountry` | `articles.metadata.sourcecountry` | outlet's estimated home country — **not** what the article is about |
| `language` | `articles.metadata.language` | filtered to English via `sourcelang:english` in the query |
| — | `articles.summary` | always `None` — DOC API has no snippet/short-description field |
| — | `articles.body` | populated via a Trafilatura fetch after DOC API returns the URL (~80% success rate observed live) |

## Other constraints

- `maxrecords=250` per query, no pagination — a single day of high-volume conflict coverage for one theme can exceed this and silently truncate (no error, just fewer results)
- 3-month rolling window only (`timespan` clamped to 90 days in code) — no historical backfill
- Attribution: GDELT's terms require crediting "the GDELT Project" if article data is republished downstream (e.g. in a digest)

---

# OFAC Sanctions List Service (explored, not integrated)

Reference for the OFAC Sanctions List Service — explored as a candidate source, not yet added to `geopolitical_news`.

## Summary

| | |
|---|---|
| **Domain** | Not integrated — no `source_type` added |
| **API** | [ofac.treasury.gov/sanctions-list-service](https://ofac.treasury.gov/sanctions-list-service) |
| **Real backend** | `https://sanctionslistservice.ofac.treas.gov` (found via SPA bundle reverse-engineering) |
| **Simplest access** | Legacy static endpoint `https://www.treasury.gov/ofac/downloads/sdn.xml` — plain GET, no auth, ~28MB, 19,254 records |
| **Auth** | None required |

## What it gives you

Fields present in the SDN List (SDN.XML), confirmed against the live file:

- **Core**: `uid`, `firstName`/`lastName`, `title`, `sdnType` (Individual/Entity/Vessel/Aircraft), `remarks`
- **Program**: `programList` → sanctions program codes (e.g. `SDGT`, `FTO`, `CUBA`, `DPRK` — 100+ codes)
- **Aliases**: `akaList` — type (a.k.a./f.k.a.), category (strong/weak), name
- **ID documents**: `idList` — passport/national ID numbers, tax IDs, **crypto wallet addresses** (BTC/ETH/TRX), org type/established date, EO citations
- **Biographical**: date of birth, place of birth, nationality, citizenship (individuals only)
- **Address**: address lines, city, state/province, postal code, country
- **Vessel-specific**: call sign, flag, owner, type, tonnage
- **File-level only**: one global `Publish_Date` — no per-record publish date, no title/summary/URL per entry

## Notes for future reference

- This is a **lookup/reference dataset** (who is currently sanctioned), not a news/document feed — it does **not** fit the `articles` table shape (no per-record title, summary, url, or published date).
- Fundamentally different from the Federal Register source above: Federal Register gives *event documents* ("OFAC added X on this date"); this gives *current list state* (who's sanctioned right now).
- To use this for `geopolitical_news`, it would need a different pattern than the existing fetch pipeline — e.g. a daily diff job (compare today's SDN.xml against yesterday's snapshot, emit "added"/"removed" entries as pseudo-articles) or a standalone name-screening/lookup feature, not a `source_type` fetch-and-store integration.
- The new SPA-backed API (`sanctionslistservice.ofac.treas.gov`) requires POST with undocumented JSON body shapes for anything beyond the file manifest (`/api/PublicationPreview/SdnList` and `/ConsolidatedList` work with `POST {}`; `/DownloadExport`, `/GetDeltaFileArchive`, and `/api/Search/Search` all need body fields that weren't reverse-engineered). No public Swagger/API docs found — a referenced `APIDocumentation.docx` 404s at every guessed path.
- The legacy `treasury.gov/ofac/downloads/sdn.xml` endpoint is the reliable path if this is ever integrated — plain GET, no request-shape guessing.
</content>
