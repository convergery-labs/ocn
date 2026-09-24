"""Fetch + knowledge_time construction for the macro_signal domain (FRED +
Treasury Fiscal Data). Fetch/store only, per this service's own boundary -
no scoring, no tiering, no LLM calls; that all lives in
signal-detection-agent's macro_signal pipeline.

Deliberately NOT wired into pipeline.py's _fetch_articles/run() dispatch -
macro_observations isn't article-shaped data (needs full-history retention,
typed range queries, ALFRED vintage tracking), so this domain bypasses
POST /run and GET /runs entirely, same as how fetch_customs_export_backfill
in pipeline.py is a standalone function called directly from a dedicated
__main__.py command rather than through run().
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from macro_release_times import (
    KnowledgeTimeDropped,
    KNOWN_FIXED_LAG_NEXT_BUSINESS_DAY_TIME,
    SERIES_RELEASE_ID,
    knowledge_time_for_observation,
)

logger = logging.getLogger(__name__)

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_FRED_RELEASE_DATES_BASE = "https://api.stlouisfed.org/fred/release/dates"
_TREASURY_DTS_BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"

# The spec's First-Print Rule boundary: ALFRED's vintage archive doesn't
# reach reliably further back than this, so anything before it is treated
# as a lower-confidence (revised-data) period via plain FRED calls, and
# only observations from this date forward use ALFRED first-print vintages.
FRED_FIRST_PRINT_CUTOFF = date(2015, 1, 1)

# The pipeline's z-score only ever reads a rolling 2-year window
# (signal-detection-agent's MACRO_SIGNAL_ZSCORE_WINDOW_DAYS=730) - nothing
# downstream reads older data. Fetching each series' FULL history (some
# back to the 1940s) costs real time (ALFRED verification calls scale
# with history depth) and storage for data nothing ever uses. 3 years =
# the 2-year window plus a 1-year buffer, so the window is always fully
# populated even right after a fresh install, without carrying decades
# of otherwise-unused history.
FETCH_LOOKBACK_DAYS = 3 * 365

# The 46-series universe. `revised` drives the First-Print Rule branch;
# series with source_type='treasury_fiscal' skip FRED entirely.
MACRO_SERIES_UNIVERSE: list[dict[str, Any]] = [
    # Background state variables (24, minus DFEDTARU handled the same as any other - it's excluded from TIERING downstream, not from fetching)
    {"series_id": "DFII10", "revised": False, "channel": "discount_rate"},
    {"series_id": "DFII5", "revised": False, "channel": "discount_rate"},
    {"series_id": "T10YIE", "revised": False, "channel": "discount_rate"},
    {"series_id": "T5YIFR", "revised": False, "channel": "discount_rate"},
    {"series_id": "T10Y2Y", "revised": False, "channel": "discount_rate"},
    {"series_id": "T10Y3M", "revised": False, "channel": "discount_rate"},
    {"series_id": "DGS10", "revised": False, "channel": "discount_rate"},
    {"series_id": "DGS3MO", "revised": False, "channel": "policy_path"},
    {"series_id": "DGS2", "revised": False, "channel": "policy_path"},
    {"series_id": "DGS1", "revised": False, "channel": "policy_path"},
    {"series_id": "DFF", "revised": False, "channel": "policy_path"},
    {"series_id": "DFEDTARU", "revised": False, "channel": "policy_path"},
    {"series_id": "FEDTARMD", "revised": False, "channel": "policy_path"},
    {"series_id": "BAA10Y", "revised": False, "channel": "credit"},
    {"series_id": "NFCI", "revised": False, "channel": "credit"},
    {"series_id": "ANFCI", "revised": False, "channel": "credit"},
    {"series_id": "NFCICREDIT", "revised": False, "channel": "credit"},
    {"series_id": "DRTSCILM", "revised": False, "channel": "credit"},
    {"series_id": "WALCL", "revised": False, "channel": "liquidity"},
    {"series_id": "RRPONTSYD", "revised": False, "channel": "liquidity"},
    {"series_id": "WTREGEN", "revised": False, "channel": "liquidity"},
    {"series_id": "WRESBAL", "revised": False, "channel": "liquidity"},
    {"series_id": "TOTRESNS", "revised": False, "channel": "liquidity"},
    {"series_id": "DTWEXBGS", "revised": False, "channel": "currency"},
    # Early-arriving hard data (5)
    {"series_id": "ICSA", "revised": False, "channel": "real_economy"},
    {"series_id": "WEI", "revised": False, "channel": "real_economy"},
    {"series_id": "GACDFSA066MSFRBPHI", "revised": False, "channel": "real_economy"},
    {"series_id": "NEWORDER", "revised": True, "channel": "real_economy"},
    {"series_id": "close_today_bal", "revised": False, "channel": "liquidity", "source_type": "treasury_fiscal"},
    # Consumer and market-facing (17)
    {"series_id": "CPIAUCSL", "revised": True, "channel": "policy_path"},
    {"series_id": "CPILFESL", "revised": True, "channel": "policy_path"},
    {"series_id": "PCEPILFE", "revised": True, "channel": "policy_path"},
    {"series_id": "PAYEMS", "revised": True, "channel": "real_economy"},
    {"series_id": "UNRATE", "revised": True, "channel": "real_economy"},
    {"series_id": "SAHMREALTIME", "revised": True, "channel": "real_economy"},
    {"series_id": "JTSJOL", "revised": True, "channel": "real_economy"},
    {"series_id": "CCSA", "revised": False, "channel": "real_economy"},
    {"series_id": "RSAFS", "revised": True, "channel": "real_economy"},
    {"series_id": "HOUST", "revised": True, "channel": "real_economy"},
    {"series_id": "PERMIT", "revised": True, "channel": "real_economy"},
    {"series_id": "MORTGAGE30US", "revised": False, "channel": "discount_rate"},
    {"series_id": "CSUSHPINSA", "revised": True, "channel": "real_economy"},
    {"series_id": "TOTALSL", "revised": True, "channel": "credit"},
    {"series_id": "DRCCLACBS", "revised": True, "channel": "credit"},
    {"series_id": "VIXCLS", "revised": False, "channel": "risk_appetite"},
    {"series_id": "VXVCLS", "revised": False, "channel": "risk_appetite"},
]

assert len(MACRO_SERIES_UNIVERSE) == 46, f"expected 46 series, got {len(MACRO_SERIES_UNIVERSE)}"


_FRED_RATE_LIMIT_MAX_RETRIES = 3


def _fred_get(params: dict[str, Any], api_key: str, timeout: float = 30.0) -> dict[str, Any]:
    """A 46-series full-history fetch makes hundreds of FRED calls
    (confirmed live: the verified release-date resolver alone can hit
    FRED's per-request rate limit under this volume, 429s observed for
    real during a live run) - a bounded retry with backoff on 429 keeps
    one rate-limit blip from silently dropping an observation that a
    few seconds' wait would have recovered. Any other error status
    raises immediately, no retry - a genuine 400/500 won't fix itself."""
    import time as _time

    full_params = {**params, "api_key": api_key, "file_type": "json"}
    last_exc: httpx.HTTPStatusError | None = None
    for attempt in range(_FRED_RATE_LIMIT_MAX_RETRIES):
        resp = httpx.get(_FRED_BASE, params=full_params, timeout=timeout)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp.json()
        last_exc = httpx.HTTPStatusError(
            f"429 rate limited (attempt {attempt + 1}/{_FRED_RATE_LIMIT_MAX_RETRIES})",
            request=resp.request, response=resp,
        )
        _time.sleep(2 ** attempt)  # 1s, 2s, 4s
    raise last_exc


# CONFIRMED LIVE: without this cache, the verified release-date resolver
# re-fetches the exact same (series_id, vintage) ALFRED call over and
# over - one observation's candidate search can overlap heavily with its
# neighbors' (a 200-day window means many nearby monthly observations
# consider the same handful of release dates as candidates), and each
# considers the SAME vintage independently with no memory between them.
# Confirmed on a real run: NEWORDER alone made 311 HTTP calls for a
# ~36-observation, 3-year window because the same handful of vintage
# dates were each fetched 5-6 times. A vintage's contents never change
# once published, so this is safe to cache for the life of one process.
_vintage_fetch_cache: dict[tuple[str, date], list[dict[str, Any]]] = {}


def _fetch_fred_observations(
    series_id: str, api_key: str, *, vintage: date | None = None,
    observation_start: date | None = None,
) -> list[dict[str, Any]]:
    """One call to fred/series/observations. vintage=None is a plain call
    (latest values, output_type default=1) - never cached, since a plain
    call's meaning depends on "now". vintage=<date> is an ALFRED
    first-print call: vintage_dates=<date>, output_type=4 ("initial
    release only") - cached per (series_id, vintage), since a published
    vintage's contents are immutable. observation_start bounds how far
    back FRED returns data - FRED's own param name, passed through
    directly."""
    if vintage is not None:
        cache_key = (series_id, vintage)
        if cache_key in _vintage_fetch_cache:
            return _vintage_fetch_cache[cache_key]

    params: dict[str, Any] = {"series_id": series_id}
    if vintage is not None:
        params["vintage_dates"] = vintage.isoformat()
        params["output_type"] = 4
    if observation_start is not None:
        params["observation_start"] = observation_start.isoformat()
    data = _fred_get(params, api_key)
    observations = data.get("observations", [])

    if vintage is not None:
        _vintage_fetch_cache[(series_id, vintage)] = observations
    return observations


_release_date_cache: dict[int, dict[date, date]] = {}


def _fred_release_dates(release_id: int, api_key: str) -> dict[date, date]:
    """observation-period-adjacent lookup: returns {date: date} mapping
    each entry FRED's own release-dates endpoint returns to itself -
    used as a set of known real release dates for a release_id, cached
    per fetch run (26 releases total, well within FRED's free-tier
    limits) since every observation from the same release shares this
    lookup."""
    if release_id in _release_date_cache:
        return _release_date_cache[release_id]
    params = {"release_id": release_id, "api_key": api_key, "file_type": "json"}
    resp = httpx.get(_FRED_RELEASE_DATES_BASE, params=params, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    dates = {
        date.fromisoformat(d["date"]): date.fromisoformat(d["date"])
        for d in data.get("release_dates", [])
    }
    _release_date_cache[release_id] = dates
    return dates


# Widened from an original 75 days after two real series failed live:
# DRCCLACBS (quarterly, Fed charge-off/delinquency data) has a confirmed
# 142-day publication lag - the 2023-07-01 observation wasn't published
# until 2023-11-20, a different quarter's release entirely. 200 days
# covers that with margin for any other quarterly-or-slower series.
_RELEASE_DATE_SEARCH_FORWARD_DAYS = 200
# FEDTARMD's own observation_date convention is the YEAR the dot-plot
# projects FOR (e.g. "2026-01-01" represents "what the Fed expects the
# rate to be during 2026"), not the date data covers up to - so its real
# publication date is the SEP release that PRODUCED that projection,
# which lands BEFORE the nominal observation_date (confirmed live: the
# 2026-01-01 observation's real release date is 2025-12-10, ~3 weeks
# earlier). A forward-only search finds nothing for this series. Search
# backward too, bounded the same distance, for any series with this
# lead-rather-than-lag convention.
_RELEASE_DATE_SEARCH_BACKWARD_DAYS = 60


def _release_date_candidates(series_id: str, observation_date: date, api_key: str) -> list[date]:
    """Candidate release dates for one observation, ordered by ABSOLUTE
    distance from observation_date (nearest first), searching both
    forward (the normal case: data covers up to observation_date,
    published afterward) and backward (FEDTARMD's lead convention - see
    _RELEASE_DATE_SEARCH_BACKWARD_DAYS).

    CONFIRMED LIVE that forward-first (rather than nearest-first)
    ordering picks the WRONG candidate for FEDTARMD: its real release
    for the 2026-01-01 observation is 22 days backward (2025-12-10), but
    a forward-only or forward-first search finds a 76-day-forward
    candidate (2026-03-18) that also happens to exist on the release
    calendar (a later, unrelated SEP) and wrongly returns that first for
    the cheap (unverified) resolver, which has no way to reject it.
    Nearest-first ordering fixes this without needing to know in advance
    which series lead vs. lag.
    """
    release_id = SERIES_RELEASE_ID.get(series_id)
    if release_id is None:
        return []
    dates = _fred_release_dates(release_id, api_key)
    window_start = observation_date - timedelta(days=_RELEASE_DATE_SEARCH_BACKWARD_DAYS)
    window_end = observation_date + timedelta(days=_RELEASE_DATE_SEARCH_FORWARD_DAYS)
    candidates = [d for d in dates if window_start <= d <= window_end]
    return sorted(candidates, key=lambda d: abs((d - observation_date).days))


def _resolve_release_date_for_observation_verified(
    series_id: str, observation_date: date, api_key: str,
) -> date | None:
    """Finds the real release date FRED associates with this observation,
    VERIFIED against a real ALFRED output_type=4 call per candidate -
    use only when the actual vintage to fetch matters (the ALFRED
    first-print branch below), since this is expensive (up to one extra
    HTTP call per candidate release date tried).

    CONFIRMED LIVE this is NOT simply "the earliest release date on or
    after observation_date" - CPI/PAYEMS-style monthly series publish
    ~6 weeks after month-end, so the closest candidate date is often a
    DIFFERENT month's release, not this observation's own first-print
    date (e.g. the 2015-01-01 CPILFESL observation's real release date
    is 2015-02-26, not 2015-01-16, which is the release date for the
    PRIOR month's observation). Taking the nearest candidate by date
    proximity alone silently attaches the wrong vintage - confirmed live
    this produced ~100% data loss for every revised series' post-2015
    history when first built with date-proximity-only matching.
    """
    for candidate in _release_date_candidates(series_id, observation_date, api_key):
        try:
            vintage_obs = _fetch_fred_observations(series_id, api_key, vintage=candidate)
        except Exception:
            continue
        if any(o["date"] == observation_date.isoformat() and o["value"] != "." for o in vintage_obs):
            return candidate
    return None


def _resolve_release_date_for_observation_cheap(
    series_id: str, observation_date: date, api_key: str,
) -> date | None:
    """Finds a real, on-calendar release date for knowledge_time
    construction ONLY - no ALFRED verification, since knowledge_time_for_
    observation just needs a real date that appears on this release_id's
    calendar (any date on that calendar is a genuine publication event
    for this series), not proof it's THIS specific observation's own
    first-print vintage. Used for never-revised series (which never call
    the verified resolver at all) and for pre-FRED_FIRST_PRINT_CUTOFF
    observations of revised series (where the plain-FRED value already
    IS what was published - ALFRED verification would be redundant, and
    ALFRED's own vintage archive doesn't reliably reach this far back
    per the spec's own First-Print Rule note).

    Same window-search shape as the verified resolver but without the
    per-candidate HTTP round-trip - the nearest forward candidate is
    accepted directly (falling back to the nearest backward candidate
    for a lead-convention series like FEDTARMD - see
    _RELEASE_DATE_SEARCH_BACKWARD_DAYS). This is a real, if small,
    accuracy tradeoff on the EXACT publication date for a revised
    series' pre-cutoff rows (matching a monthly-release-shaped series to
    its true ~6-week-later print isn't guaranteed here), traded for not
    making one extra HTTP call per observation on every fetch run.
    """
    candidates = _release_date_candidates(series_id, observation_date, api_key)
    return candidates[0] if candidates else None


_FEDTARMD_VINTAGE_DATES_URL = "https://api.stlouisfed.org/fred/series/vintagedates"


def _fetch_fedtarmd(api_key: str, *, lookback_days: int | None = None) -> list[dict[str, Any]]:
    """FEDTARMD (SEP median dot-plot) does not fit the plain revised/
    never-revised shape every other series uses - CONFIRMED LIVE: a plain
    (no-vintage) fred/series/observations call only ever returns the
    LATEST SEP's projections, with every already-passed target year gone
    blank (the Fed stops projecting a year once it arrives) - e.g. as of
    the 2026-09 SEP, 2023/2024/2025 all read "." and only 2026-2029 have
    values. There is no stable "history" to page through with
    observation_start the way every other series has.

    The real history is the sequence of SEP releases themselves (~4/yr,
    fred/series/vintagedates), each a point-in-time snapshot of the full
    dot-plot fetched via realtime_start=realtime_end=<vintage date>
    (CONFIRMED LIVE this is the shape that actually returns each
    snapshot's own values - vintage_dates+output_type=4, the mechanism
    every other revised series here uses for ALFRED first-print data,
    returns almost nothing for this series).

    Stores ONE ROW PER (release, target_year) PAIR - a single SEP release
    projects several future years at once (e.g. the 2026-09-16 release
    projects 2026 through 2029), and signal-detection-agent's
    sep_median_shift_bp needs to compare the SAME target year across two
    CONSECUTIVE releases (e.g. "what did Sept's SEP say about 2027" vs
    "what did June's SEP say about 2027") - comparing each release's own
    "next year relative to itself" would silently compare different
    target years across a calendar-year boundary (e.g. Dec's 2026 dot vs
    the following March's 2027 dot), which is not a real comparison.
    observation_date is the target year's own FRED convention (Jan 1 of
    that year, matching the raw series' own dating), vintage is the real
    SEP release date - so (series_id, observation_date, vintage) stays a
    real, distinct key per (release, target_year), and the standard
    upsert index needs no change.
    """
    lookback_days = lookback_days if lookback_days is not None else FETCH_LOOKBACK_DAYS
    fetch_start = date.today() - timedelta(days=lookback_days)

    resp = httpx.get(
        _FEDTARMD_VINTAGE_DATES_URL,
        params={"series_id": "FEDTARMD", "api_key": api_key, "file_type": "json"},
        timeout=30.0,
    )
    resp.raise_for_status()
    vintage_dates = [
        date.fromisoformat(d) for d in resp.json().get("vintage_dates", [])
    ]
    vintage_dates = [d for d in vintage_dates if d >= fetch_start]

    rows: list[dict[str, Any]] = []
    dropped = 0
    for vintage in vintage_dates:
        data = _fred_get(
            {"series_id": "FEDTARMD", "realtime_start": vintage.isoformat(), "realtime_end": vintage.isoformat()},
            api_key,
        )
        snapshot = {
            date.fromisoformat(o["date"]): float(o["value"])
            for o in data.get("observations", []) if o["value"] != "."
        }
        if not snapshot:
            dropped += 1
            logger.warning("[MACRO_FETCH] FEDTARMD vintage=%s: empty snapshot, dropping this release", vintage)
            continue
        try:
            kt, confidence = knowledge_time_for_observation("FEDTARMD", vintage, vintage)
        except KnowledgeTimeDropped as exc:
            dropped += 1
            logger.warning("[MACRO_FETCH] dropped FEDTARMD vintage=%s: %s", vintage, exc)
            continue
        for target_year_date, median in snapshot.items():
            rows.append({
                "series_id": "FEDTARMD",
                "observation_date": target_year_date,
                "value": median,
                "knowledge_time": kt,
                "knowledge_time_confidence": confidence,
                "vintage": vintage,
                "source": "fred_alfred",
                "raw_payload": {"sep_release_date": vintage.isoformat(), "target_year": target_year_date.year, "median": median},
            })
    if dropped:
        logger.warning("[MACRO_FETCH] FEDTARMD: dropped %d SEP releases (no usable snapshot), stored %d (release, target_year) rows",
                        dropped, len(rows))
    return rows


def _fetch_one_fred_series(
    series_cfg: dict[str, Any], api_key: str, *, lookback_days: int | None = None,
) -> list[dict[str, Any]]:
    """Fetches one series' history (bounded to lookback_days, default
    FETCH_LOOKBACK_DAYS - the pipeline never reads further back than its
    own rolling z-score window, see FETCH_LOOKBACK_DAYS's own comment)
    per the First-Print Rule: plain FRED calls for
    observation_date < FRED_FIRST_PRINT_CUTOFF, ALFRED output_type=4
    vintage calls from that date forward for revised series; always
    plain calls for never-revised series. Resolves knowledge_time per
    observation, silently skipping (never inserting) any observation
    that KnowledgeTimeDropped rejects - counted and logged, not guessed.

    Returns rows ready for insert_macro_observations().
    """
    series_id = series_cfg["series_id"]
    revised = series_cfg["revised"]
    lookback_days = lookback_days if lookback_days is not None else FETCH_LOOKBACK_DAYS
    fetch_start = date.today() - timedelta(days=lookback_days)

    # (observation_dict, vintage_or_None, release_date_or_None). vintage
    # is set only for a real ALFRED first-print row; release_date is
    # whatever was actually resolved for that row (threaded through
    # directly here so the expensive verified resolver is never called
    # twice for the same row - it was already run once to pick which
    # vintage to fetch below).
    raw_rows: list[tuple[dict[str, Any], date | None, date | None]] = []

    if revised:
        # One plain call, bounded to fetch_start, split locally into
        # pre/post cutoff rather than two separate identical FRED calls
        # (the original shape fetched the same series twice with no
        # different params - wasteful, fixed here).
        all_plain = _fetch_fred_observations(series_id, api_key, observation_start=fetch_start)
        pre_cutoff_obs = [
            o for o in all_plain
            if o["value"] != "." and date.fromisoformat(o["date"]) < FRED_FIRST_PRINT_CUTOFF
        ]
        for o in pre_cutoff_obs:
            raw_rows.append((o, None, None))  # release_date resolved cheaply below

        post_cutoff_dates = [
            date.fromisoformat(o["date"]) for o in all_plain
            if o["value"] != "." and date.fromisoformat(o["date"]) >= FRED_FIRST_PRINT_CUTOFF
        ]
        for obs_date in post_cutoff_dates:
            # FRED's output_type=4 requires vintage_dates to be an actual
            # RELEASE date for this series, not the observation date
            # itself (confirmed live: "Vintage date is not a release
            # date for this series") - and not just the nearest release
            # calendar date either (confirmed live: CPI/PAYEMS-style
            # series publish ~6 weeks after month-end, so nearest-by-date
            # often lands on the WRONG month's release). The verified
            # resolver tries each candidate against a real ALFRED call
            # until one actually contains this observation.
            release_date = _resolve_release_date_for_observation_verified(series_id, obs_date, api_key)
            if release_date is None:
                continue  # no resolvable release date - this observation is dropped, not guessed
            try:
                vintage_obs = _fetch_fred_observations(series_id, api_key, vintage=release_date)
            except Exception as exc:
                # A resolved candidate can still fail at fetch time (rate
                # limit, transient error) - one bad observation must not
                # lose every later observation in this series' fetch.
                logger.warning(
                    "[MACRO_FETCH] %s %s: ALFRED call for resolved release_date=%s failed, skipping this observation: %s",
                    series_id, obs_date, release_date, exc,
                )
                continue
            match = next((o for o in vintage_obs if o["date"] == obs_date.isoformat() and o["value"] != "."), None)
            if match is not None:
                raw_rows.append((match, release_date, release_date))
    else:
        plain_obs = _fetch_fred_observations(series_id, api_key, observation_start=fetch_start)
        raw_rows = [(o, None, None) for o in plain_obs if o["value"] != "."]

    rows: list[dict[str, Any]] = []
    dropped = 0
    for obs, vintage, resolved_release_date in raw_rows:
        obs_date = date.fromisoformat(obs["date"])
        # Reuse the already-resolved release date for a post-cutoff ALFRED
        # row (never-revised or pre-cutoff rows resolve cheaply here - no
        # ALFRED verification needed, knowledge_time just needs a real
        # on-calendar release date, not proof of vintage correctness).
        release_date = resolved_release_date or _resolve_release_date_for_observation_cheap(
            series_id, obs_date, api_key,
        )
        try:
            kt, confidence = knowledge_time_for_observation(series_id, obs_date, release_date)
        except KnowledgeTimeDropped as exc:
            dropped += 1
            logger.warning("[MACRO_FETCH] dropped %s %s: %s", series_id, obs_date, exc)
            continue
        rows.append({
            "series_id": series_id,
            "observation_date": obs_date,
            "value": float(obs["value"]),
            "knowledge_time": kt,
            "knowledge_time_confidence": confidence,
            "vintage": vintage,
            "source": "fred_alfred" if vintage is not None else "fred",
            "raw_payload": obs,
        })
    if dropped:
        logger.warning("[MACRO_FETCH] %s: dropped %d/%d observations (no verified knowledge_time)",
                        series_id, dropped, dropped + len(rows))
    return rows


# Treasury's DTS operating_cash_balance table changed shape twice,
# confirmed live 2026-09-24 - close_today_bal cannot be fetched with one
# fixed filter/field combination across the full history:
#   through 2021-09-30: account_type='Federal Reserve Account',
#     value in close_today_bal
#   2021-10-01 through 2022-04-15: account_type='Treasury General
#     Account (TGA)', value still in close_today_bal
#   2022-04-18 onward: the table was restructured into
#     Opening/Deposits/Withdrawals/Closing rows per date;
#     close_today_bal is 'null' on every row now - the actual closing
#     balance for a date lives in open_today_bal on the row where
#     account_type='Treasury General Account (TGA) Closing Balance'
#     (Treasury's own field naming, despite reading like an opening
#     value - confirmed by checking real duplicate-date rows).
_TREASURY_ACCOUNT_TYPE_ERAS: list[tuple[str, str]] = [
    ("Federal Reserve Account", "close_today_bal"),
    ("Treasury General Account (TGA)", "close_today_bal"),
    ("Treasury General Account (TGA) Closing Balance", "open_today_bal"),
]


def fetch_treasury_fiscal(
    api_key: str | None = None, *, lookback_days: int | None = None,
) -> list[dict[str, Any]]:
    """Fetches close_today_bal's history (bounded to lookback_days,
    default FETCH_LOOKBACK_DAYS - see that constant's own comment) from
    Treasury Fiscal Data's DTS operating cash balance endpoint (open, no
    key required - api_key param accepted for signature symmetry only,
    unused). Queries each known account_type era separately (see
    _TREASURY_ACCOUNT_TYPE_ERAS) and merges - a single filter/field pair
    does not cover this table's full history, since Treasury has
    renamed/restructured it twice.
    """
    series_id = "close_today_bal"
    rows: list[dict[str, Any]] = []
    dropped = 0
    lookback_days = lookback_days if lookback_days is not None else FETCH_LOOKBACK_DAYS
    fetch_start = date.today() - timedelta(days=lookback_days)

    for account_type, value_field in _TREASURY_ACCOUNT_TYPE_ERAS:
        page = 1
        page_size = 500
        while True:
            params = {
                "fields": f"record_date,account_type,{value_field}",
                "filter": f"account_type:eq:{account_type},record_date:gte:{fetch_start.isoformat()}",
                "page[number]": page,
                "page[size]": page_size,
                "sort": "record_date",
            }
            resp = httpx.get(_TREASURY_DTS_BASE, params=params, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("data", [])
            if not batch:
                break
            for row in batch:
                try:
                    obs_date = date.fromisoformat(row["record_date"])
                    value = float(row[value_field])
                except (KeyError, ValueError, TypeError):
                    continue
                try:
                    kt, confidence = knowledge_time_for_observation(series_id, obs_date, None)
                except KnowledgeTimeDropped as exc:
                    dropped += 1
                    logger.warning("[MACRO_FETCH] dropped %s %s: %s", series_id, obs_date, exc)
                    continue
                rows.append({
                    "series_id": series_id,
                    "observation_date": obs_date,
                    "value": value,
                    "knowledge_time": kt,
                    "knowledge_time_confidence": confidence,
                    "vintage": None,
                    "source": "treasury_fiscal",
                    "raw_payload": row,
                })
            total_pages = data.get("meta", {}).get("total-pages", page)
            if page >= total_pages:
                break
            page += 1
    if dropped:
        logger.warning("[MACRO_FETCH] close_today_bal: dropped %d observations", dropped)
    return rows


# An incremental run fetches this fixed short window, not a
# watermark-based calculation - no per-series DB lookup needed, just a
# constant. 1 day (not 2) since this now runs TWICE daily, 12 hours
# apart (see infra's own news_retrieval_macro_signals_daily schedule
# comment) - the two runs' own 1-day windows already overlap enough to
# cover a single failed run or a knowledge_time landing just after
# midnight UTC without needing extra margin on top; the wider 2-day
# window was sized for the original once-a-day cadence and became
# redundant once the schedule doubled.
INCREMENTAL_LOOKBACK_DAYS = 1


def fetch_all_macro_signals(
    fred_api_key: str, *, incremental: bool = False,
) -> list[dict[str, Any]]:
    """Fetches all 46 series (45 FRED + 1 Treasury Fiscal Data), returning
    rows ready for insert_macro_observations().

    incremental=False (default): full FETCH_LOOKBACK_DAYS (3 years)
    re-pull per series - the one-time initial backfill, or a deliberate
    re-backfill.

    incremental=True: fixed INCREMENTAL_LOOKBACK_DAYS (1 day) fetch per
    series, every run, regardless of what's already stored - the
    intended mode for a twice-daily scheduled run once the initial
    3-year backfill has been run once. Simple and stateless: no
    watermark lookup, no per-series DB query before fetching - always
    the same small window, upserted safely over whatever's already
    there.

    One series' fetch failing (a FRED API error, a malformed response,
    etc.) does not abort the whole run - logged and skipped, so a bad
    day for one series' upstream data never blocks the other 45."""
    lookback_days = INCREMENTAL_LOOKBACK_DAYS if incremental else None  # None -> callees' own FETCH_LOOKBACK_DAYS default

    all_rows: list[dict[str, Any]] = []
    for series_cfg in MACRO_SERIES_UNIVERSE:
        series_id = series_cfg["series_id"]
        try:
            if series_cfg.get("source_type") == "treasury_fiscal":
                rows = fetch_treasury_fiscal(lookback_days=lookback_days)
            elif series_id == "FEDTARMD":
                rows = _fetch_fedtarmd(fred_api_key, lookback_days=lookback_days)
            else:
                rows = _fetch_one_fred_series(series_cfg, fred_api_key, lookback_days=lookback_days)
        except Exception:
            logger.exception("[MACRO_FETCH] %s: fetch failed, skipping this series", series_id)
            continue
        logger.info(
            "[MACRO_FETCH] %s: %d observations (lookback_days=%s)",
            series_id, len(rows), lookback_days if lookback_days is not None else FETCH_LOOKBACK_DAYS,
        )
        all_rows.extend(rows)
    return all_rows
