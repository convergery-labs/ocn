"""Z-SCORE (spec section 2 step 3): change and rolling z-score computation
from raw macro_observations rows. Pure arithmetic, no DB/LLM - validated
standalone against real FRED data before this service existed (Step 0 of
the Macro Signal Backbone build); ported here as the real module once
that validation matched the spec's own worked example (DFII5 z~=2.445,
DGS1 z~=2.905 on 2026-08-28)."""
from __future__ import annotations

import statistics
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import config


def compute_daily_changes(observations: list[dict[str, Any]]) -> dict[date, float]:
    """Day-over-day change in native bp (value is in percent, as FRED
    returns rate/yield series; * 100 -> bp), keyed by observation_date.
    `observations` must be for a SINGLE series, any order - sorted here.

    CONFIRMED LIVE (real frontend ticket, 2026-09-25, job 262): computing
    this via float(value) then float arithmetic (e.g. 0.31 - 0.26) picks
    up binary-float imprecision (e.g. 4.999999999999996 for a real exact
    5bp move) - a later truncation step meant to clean this up made it
    WORSE (truncating 4.999999999999996 gives 4.99, not 5, since the
    true value's float representation can land on either side of the
    real integer). Fixed at the source instead: Decimal on the raw
    string value (Postgres numeric -> str, e.g. "0.31") is exact, so the
    bp change is exact too - no rounding or truncation step needed
    anywhere downstream. Still returns float (the z-score/tier pipeline
    downstream is float-based statistics, where exactness doesn't
    matter) - only the intermediate arithmetic uses Decimal."""
    by_date = {o["observation_date"]: Decimal(str(o["value"])) for o in observations if o.get("value") is not None}
    dates = sorted(by_date.keys())
    changes: dict[date, float] = {}
    for i in range(1, len(dates)):
        prev_d, cur_d = dates[i - 1], dates[i]
        changes[cur_d] = float((by_date[cur_d] - by_date[prev_d]) * 100)
    return changes


def rolling_zscore(
    changes: dict[date, float], window_days: int | None = None,
) -> dict[date, float]:
    """Z-score of each day's change against the stddev of changes in the
    trailing window_days (calendar days). Requires >=30 observations in
    the window before computing (an arbitrary but sane minimum sample -
    fewer than that and a stddev is not a meaningful denominator)."""
    window_days = window_days or config.MACRO_SIGNAL_ZSCORE_WINDOW_DAYS
    dates = sorted(changes.keys())
    z: dict[date, float] = {}
    for d in dates:
        window_start = d - timedelta(days=window_days)
        window_vals = [changes[wd] for wd in dates if window_start <= wd < d]
        if len(window_vals) < 30:
            continue
        stdev = statistics.pstdev(window_vals)
        if stdev == 0:
            continue
        z[d] = changes[d] / stdev
    return z


def compute_series_zscores(
    observations: list[dict[str, Any]], window_days: int | None = None,
) -> dict[date, tuple[float, float]]:
    """Convenience wrapper: returns {date: (change_bp, z_score)} for every
    date with a computable z-score, for one series' observations."""
    changes = compute_daily_changes(observations)
    zscores = rolling_zscore(changes, window_days)
    return {d: (changes[d], zscores[d]) for d in zscores}
