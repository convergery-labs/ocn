"""FEDTARMD's sep_median_shift_bp computation (spec section 7's FEDTARMD
z-gate exception: "next-year median shift >= 25bp vs prior SEP, no
z-gate").

news-retrieval stores FEDTARMD as one row per (SEP release, projected
target year) - observation_date is the target year's own FRED convention
(Jan 1 of that year), vintage is the real SEP release date (see
news-retrieval's macro_signal_fetch._fetch_fedtarmd for why: a single SEP
release projects several future years at once, e.g. the 2026-09 release
covers 2026 through 2029, and comparing "each release's own next year
relative to itself" silently compares DIFFERENT target years across a
calendar-year boundary - not a real comparison).

The real comparison the spec means is: for two CONSECUTIVE SEP releases,
what did each say about the SAME target year - "the 2027 median moved
from 3.6% to 3.9%" comparing June's SEP and September's SEP, both talking
about 2027. This module does that comparison.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional


def _target_year_series(observations: list[dict[str, Any]]) -> dict[date, dict[int, float]]:
    """Groups FEDTARMD observations by SEP release (vintage), each a
    {target_year: median} dict. observations must all be for FEDTARMD."""
    by_release: dict[date, dict[int, float]] = {}
    for o in observations:
        vintage = o.get("vintage")
        obs_date = o.get("observation_date")
        value = o.get("value")
        if vintage is None or obs_date is None or value is None:
            continue
        by_release.setdefault(vintage, {})[obs_date.year] = float(value)
    return by_release


def compute_sep_median_shift_bp(
    observations: list[dict[str, Any]], release_date: date,
) -> Optional[float]:
    """Returns the bp shift in the SAME target year's median dot between
    `release_date`'s own SEP and the immediately PRIOR SEP release found
    in `observations` - or None if release_date isn't a known release, no
    prior release exists, or neither release projected a common target
    year (should not happen in practice - SEP releases always project
    several overlapping years - but a real gap must surface as "no
    shift computable", not a fabricated 0.0).

    Target year picked as the NEAREST future year both releases have in
    common (smallest target year > release_date.year at the earlier of
    the two releases) - this is normally release_date.year + 1, matching
    the spec's own "next-year median" phrasing, and only differs when a
    release happens to omit that year (not observed live, guarded anyway).
    """
    by_release = _target_year_series(observations)
    if release_date not in by_release:
        return None
    prior_releases = sorted(d for d in by_release if d < release_date)
    if not prior_releases:
        return None
    prior_release = prior_releases[-1]

    current = by_release[release_date]
    prior = by_release[prior_release]
    common_years = sorted(set(current) & set(prior))
    if not common_years:
        return None

    preferred_year = prior_release.year + 1
    target_year = preferred_year if preferred_year in common_years else common_years[0]

    shift_pp = current[target_year] - prior[target_year]
    return shift_pp * 100
