"""Static publication-time lookup for macro_signal knowledge_time
construction (spec section 4's data/release_times.csv, reproduced here as
a Python module rather than a DB table - a small, rarely-changing,
code-reviewed lookup, same precedent as taiwan_signal_classifier.py's
_CLAUSE_CODE_TABLE).

Every one of the 46 tracked series routes through exactly one of three
provenance tiers, in order:
  (a) verified release calendar - series_id -> release_id -> RELEASE_TIMES
      entry (a scheduled ET publication time, or None -> falls through to
      the 16:30 ET close stamp).
  (b) known fixed publication lag - series_id in KNOWN_FIXED_LAG_HOURS.
  Neither applies -> the row is dropped, never guessed at (see
  KnowledgeTimeDropped).
Daily market series (yields, VIX, the dollar) are always stamped at the
16:30 ET close regardless of any release calendar entry - listed in
DAILY_MARKET_CLOSE_SERIES.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# release_id -> (release_name, ET publication time or None, source agency).
# A None time means "no fixed scheduled-release clock time" (daily market
# data, not a data print) - falls through to the 16:30 ET close stamp.
# Verbatim from spec section 4's publication-time table.
RELEASE_TIMES: dict[int, tuple[str, time | None, str]] = {
    9: ("Advance Monthly Sales for Retail and Food Services", time(8, 30), "Census"),
    10: ("Consumer Price Index", time(8, 30), "BLS"),
    14: ("G.19 Consumer Credit", time(15, 0), "Federal Reserve"),
    17: ("H.10 Foreign Exchange Rates", None, "Federal Reserve"),
    18: ("H.15 Selected Interest Rates", time(14, 0), "FOMC"),
    20: ("H.4.1 Factors Affecting Reserve Balances", time(16, 30), "Federal Reserve"),
    21: ("H.6 Money Stock Measures", time(16, 30), "Federal Reserve"),
    27: ("New Residential Construction", time(8, 30), "Census"),
    50: ("Employment Situation", time(8, 30), "BLS"),
    54: ("Personal Income and Outlays", time(8, 30), "BEA"),
    95: ("Manufacturers' Shipments, Inventories and Orders (M3)", time(8, 30), "Census"),
    101: ("FOMC Press Release", time(14, 0), "FOMC"),
    180: ("Unemployment Insurance Weekly Claims Report", time(8, 30), "DOL"),
    190: ("Primary Mortgage Market Survey", time(12, 0), "Freddie Mac"),
    191: ("Senior Loan Officer Opinion Survey (SLOOS)", time(14, 0), "Federal Reserve"),
    192: ("Job Openings and Labor Turnover Survey", time(8, 30), "BLS"),
    199: ("S&P Cotality Case-Shiller Home Price Indices", time(9, 0), "S&P Cotality"),
    200: ("CBOE Market Statistics", None, "CBOE"),
    221: ("Chicago Fed National Financial Conditions Index", time(8, 30), "Chicago Fed"),
    231: ("Charge-Off and Delinquency Rates", time(16, 30), "Federal Reserve"),
    304: ("Interest Rate Spreads", None, "Federal Reserve"),
    326: ("Summary of Economic Projections", time(14, 0), "FOMC"),
    351: ("Manufacturing Business Outlook Survey", time(8, 30), "Philadelphia Fed"),
    379: ("Temporary Open Market Operations", None, "Federal Reserve"),
    456: ("Sahm Rule Recession Indicator", time(8, 30), "BLS"),
    465: ("Weekly Economic Index (Lewis-Mertens-Stock)", time(12, 0), "NY Fed"),
}

_CLOSE_STAMP_TIME = time(16, 30)

# series_id -> FRED release_id. Every one of the 46 tracked series that
# routes through tier (a) must appear here.
SERIES_RELEASE_ID: dict[str, int] = {
    # Background state variables
    "DFII10": 18, "DFII5": 18, "T10YIE": 18, "T5YIFR": 18,
    "T10Y2Y": 18, "T10Y3M": 18, "DGS10": 18, "DGS3MO": 18, "DGS2": 18, "DGS1": 18,
    "DFF": 18, "DFEDTARU": 18, "FEDTARMD": 326,
    "BAA10Y": 18, "NFCI": 221, "ANFCI": 221, "NFCICREDIT": 221,
    "DRTSCILM": 191, "WALCL": 20, "RRPONTSYD": 379, "WTREGEN": 20,
    "WRESBAL": 20, "TOTRESNS": 21, "DTWEXBGS": 18,
    # Early-arriving hard data
    "ICSA": 180, "WEI": 465, "GACDFSA066MSFRBPHI": 351, "NEWORDER": 95,
    # close_today_bal: no FRED release_id - Treasury Fiscal Data, tier (b) only.
    # Consumer and market-facing
    "CPIAUCSL": 10, "CPILFESL": 10, "PCEPILFE": 54,
    "PAYEMS": 50, "UNRATE": 50, "SAHMREALTIME": 456, "JTSJOL": 192,
    "CCSA": 180, "RSAFS": 9, "HOUST": 27, "PERMIT": 27,
    "MORTGAGE30US": 190, "CSUSHPINSA": 199, "TOTALSL": 14, "DRCCLACBS": 231,
    "VIXCLS": 200, "VXVCLS": 200,
}

# Series with a known fixed publication lag (tier b) instead of a release
# calendar entry. close_today_bal (Treasury Fiscal Data / DTS) has no FRED
# release calendar - Treasury's Daily Treasury Statement is published the
# next business day, reliably available by early-to-mid afternoon ET;
# using 15:00 ET as a conservative estimate of that documented SLA.
KNOWN_FIXED_LAG_HOURS: dict[str, float] = {}
KNOWN_FIXED_LAG_NEXT_BUSINESS_DAY_TIME: dict[str, time] = {
    "close_today_bal": time(15, 0),
}

# Series stamped at fixed 16:30 ET close regardless of release calendar -
# daily market series (yields, VIX, the dollar) per spec section 4.
DAILY_MARKET_CLOSE_SERIES: frozenset[str] = frozenset({
    "DFII10", "DFII5", "T10YIE", "T5YIFR", "T10Y2Y", "T10Y3M",
    "DGS10", "DGS3MO", "DGS2", "DGS1", "DFF", "DFEDTARU",
    "BAA10Y", "MORTGAGE30US", "VIXCLS", "VXVCLS", "DTWEXBGS",
})


class KnowledgeTimeDropped(Exception):
    """Raised when neither provenance tier (a) nor (b) applies - caller
    must skip the row rather than insert it with a guessed knowledge_time."""


def _next_business_day(d: date) -> date:
    """Next weekday after d (Mon-Fri). Does not account for US federal
    holidays - a real gap, but Treasury Fiscal Data's own publication
    calendar already skips holidays on its side, so this is a
    conservative (slightly early) estimate at worst, never late."""
    from datetime import timedelta
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:  # 5=Sat, 6=Sun
        nxt += timedelta(days=1)
    return nxt


def knowledge_time_for_observation(
    series_id: str,
    observation_date: date,
    release_date: date | None = None,
) -> tuple[datetime, str]:
    """Returns (knowledge_time_utc, confidence) for one observation.

    Provenance tiers, in order:
    (a) series_id in DAILY_MARKET_CLOSE_SERIES -> release_date (or
        observation_date if release_date is None) at 16:30 ET,
        confidence='verified'.
    (a) series_id in SERIES_RELEASE_ID and that release_id in
        RELEASE_TIMES -> release_date at that release's ET time (or
        16:30 ET if the release has no fixed clock time), confidence='verified'.
        Requires release_date to be given (the caller resolves this via
        FRED's fred/release/dates for the given release_id).
    (b) series_id in KNOWN_FIXED_LAG_NEXT_BUSINESS_DAY_TIME -> next
        business day after observation_date, at that lag's ET time,
        confidence='known_lag'.
    Neither applies -> raises KnowledgeTimeDropped.
    """
    if series_id in DAILY_MARKET_CLOSE_SERIES:
        base_date = release_date or observation_date
        return _et_to_utc(base_date, _CLOSE_STAMP_TIME), "verified"

    release_id = SERIES_RELEASE_ID.get(series_id)
    if release_id is not None and release_id in RELEASE_TIMES:
        if release_date is None:
            raise KnowledgeTimeDropped(
                f"{series_id}: release_id={release_id} is a verified-tier series "
                f"but no release_date was resolved - caller must fetch it via "
                f"fred/release/dates before calling this function."
            )
        _, et_time, _ = RELEASE_TIMES[release_id]
        stamp_time = et_time or _CLOSE_STAMP_TIME
        return _et_to_utc(release_date, stamp_time), "verified"

    lag_time = KNOWN_FIXED_LAG_NEXT_BUSINESS_DAY_TIME.get(series_id)
    if lag_time is not None:
        lag_date = _next_business_day(observation_date)
        return _et_to_utc(lag_date, lag_time), "known_lag"

    raise KnowledgeTimeDropped(
        f"{series_id} on {observation_date}: no verified release calendar entry "
        f"and no known fixed lag - dropping rather than guessing."
    )


def _et_to_utc(d: date, t: time) -> datetime:
    """Combines a date and ET clock time, correctly handling the EST/EDT
    boundary via zoneinfo (never a fixed offset - publication times cross
    DST, and a naive fixed offset would misstamp roughly half the year)."""
    dt_et = datetime.combine(d, t, tzinfo=_ET)
    return dt_et.astimezone(timezone.utc)
