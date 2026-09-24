"""FOMC scheduled meeting dates, needed only for DFF's inter-meeting
move detection (spec section 7, Note A): "an inter-meeting change: the
Fed's announced target moved on a date that is not a scheduled FOMC
decision date."

Stored in the fomc_meeting_dates table (see db.py), refreshed from the
Fed's own calendar.json feed by a scheduled job (refresh-fomc-calendar
CLI command / CloudWatch schedule), not hand-maintained code.

CONFIRMED LIVE (2026-09-24) this could NOT be sourced from FRED's own
release-dates endpoint: release_id=101 ("FOMC Press Release") returns
~daily entries (3791 dates for a calendar that should have ~120 real
meeting dates since 1994), not a clean meeting calendar - and
release_id=326 (Summary of Economic Projections) is clean but only
covers 4 of the Fed's 8 annual meetings. federalreserve.gov/json/
calendar.json's "FOMC Press Conference"-titled events ARE a clean,
correct, real source - confirmed live to match the Fed's own published
schedule exactly for the dates checked.

The table can still be stale (the feed only carries a forward-looking
window - confirmed live it currently covers ~11 upcoming dates, not
deep history) if the refresh job stops running - see
calendar_staleness_warning for the same "fail loud, don't guess" guard
this had when it was a hardcoded Python list, now checking the table's
own freshness instead of a fixed horizon constant.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from db import get_db

logger = logging.getLogger(__name__)

_FOMC_CALENDAR_FEED_URL = "https://www.federalreserve.gov/json/calendar.json"
_FOMC_EVENT_TITLE = "FOMC Press Conference"

# How far ahead of the last known meeting date a pipeline run should
# start warning that the table needs a refresh. The Fed's own feed is a
# rolling forward-looking window, so under normal operation (the
# refresh job actually running on schedule) this table should almost
# never approach staleness - a warning here means the refresh job
# itself has stopped running, not that the Fed hasn't published dates
# yet.
_STALENESS_WARNING_WINDOW_DAYS = 30


def fetch_fomc_meeting_dates() -> list[date]:
    """Fetches real, current FOMC Press Conference (decision announcement)
    dates from the Fed's own public calendar feed. Raises on any HTTP
    failure - callers should not silently proceed with a partial/stale
    refresh."""
    resp = httpx.get(_FOMC_CALENDAR_FEED_URL, timeout=15.0)
    resp.raise_for_status()
    # The feed's own JSON has a leading BOM (confirmed live) - strip
    # before parsing.
    import json
    data = json.loads(resp.text.lstrip("﻿"))
    events = data.get("events", [])
    dates: set[date] = set()
    for e in events:
        if (e.get("title") or "").strip() != _FOMC_EVENT_TITLE:
            continue
        month = e.get("month")  # "YYYY-MM"
        day = e.get("days")
        if not month or not day:
            continue
        try:
            year, mon = month.split("-")
            dates.add(date(int(year), int(mon), int(day)))
        except (ValueError, AttributeError):
            logger.warning("[MACRO_SIGNAL_FOMC_CALENDAR] could not parse event date: month=%r days=%r", month, day)
            continue
    return sorted(dates)


def refresh_fomc_meeting_dates() -> int:
    """Fetches the real calendar and upserts into fomc_meeting_dates.
    Returns the number of dates fetched. Never deletes existing rows -
    the feed is a rolling forward window, so an already-stored date
    that's aged out of the feed's current window is still a real past
    meeting date, not something to remove."""
    dates = fetch_fomc_meeting_dates()
    if not dates:
        raise ValueError("FOMC calendar feed returned zero FOMC Press Conference dates - refusing to proceed with an empty refresh")
    with get_db() as conn:
        for d in dates:
            conn.execute(
                """
                INSERT INTO fomc_meeting_dates (meeting_date, refreshed_at)
                VALUES (%s, NOW())
                ON CONFLICT (meeting_date) DO UPDATE SET refreshed_at = NOW()
                """,
                (d,),
            )
    return len(dates)


def _all_meeting_dates() -> frozenset[date]:
    with get_db() as conn:
        rows = conn.execute("SELECT meeting_date FROM fomc_meeting_dates").fetchall()
    return frozenset(r["meeting_date"] for r in rows)


def _latest_meeting_date() -> date | None:
    with get_db() as conn:
        row = conn.execute("SELECT MAX(meeting_date) AS d FROM fomc_meeting_dates").fetchone()
    return row["d"] if row and row["d"] else None


def _latest_refresh_time() -> datetime | None:
    with get_db() as conn:
        row = conn.execute("SELECT MAX(refreshed_at) AS t FROM fomc_meeting_dates").fetchone()
    return row["t"] if row and row["t"] else None


def is_scheduled_fomc_date(observation_date: date) -> bool:
    """observation_date is DFEDTARU's own observation_date - the date a
    RATE CHANGE first appears in FRED's daily series - NOT the date the
    Fed announced the decision. CONFIRMED LIVE against 7 real DFEDTARU
    changes since 2024: the new rate consistently appears in FRED's
    series on the CALENDAR DAY AFTER the FOMC meeting's second
    (decision) day, not on the meeting date itself - the 14:00 ET
    announcement lands after that trading day's observation is already
    set. A direct observation_date-in-meeting-dates check matched ZERO
    of the 7 real changes before this offset was found and fixed.
    """
    return (observation_date - timedelta(days=1)) in _all_meeting_dates()


def is_within_known_calendar_horizon(d: date) -> bool:
    """False means the calendar does not yet cover this date - the
    caller must not guess whether it's an FOMC date, and must not
    classify a DFF move on this date as inter-meeting (or as
    scheduled) based on this table alone."""
    horizon = _latest_meeting_date()
    if horizon is None:
        return False  # table has never been refreshed - nothing is known
    return d <= horizon


def calendar_staleness_warning(today: date) -> str | None:
    """Returns a human-readable warning if the fomc_meeting_dates table
    is empty, has never been refreshed, or its last refresh is more
    than _STALENESS_WARNING_WINDOW_DAYS old - meant to be logged once
    per pipeline run (see controllers.run.run_macro_signal_pipeline) so
    a stopped refresh-fomc-calendar schedule surfaces in ordinary
    operational logs, not silently, since the table itself has no
    other way to signal "the refresh job hasn't run in a while."
    """
    horizon = _latest_meeting_date()
    if horizon is None:
        return (
            "[MACRO_SIGNAL_FOMC_CALENDAR] fomc_meeting_dates table is empty - "
            "run 'refresh-fomc-calendar' at least once. DFF inter-meeting "
            "detection cannot function until this table has data."
        )

    last_refresh = _latest_refresh_time()
    if last_refresh is not None:
        refresh_date = last_refresh.date() if hasattr(last_refresh, "date") else last_refresh
        days_since_refresh = (today - refresh_date).days
        if days_since_refresh > _STALENESS_WARNING_WINDOW_DAYS:
            return (
                f"[MACRO_SIGNAL_FOMC_CALENDAR] fomc_meeting_dates last refreshed "
                f"{days_since_refresh} days ago (> {_STALENESS_WARNING_WINDOW_DAYS} day "
                f"threshold) - the refresh-fomc-calendar schedule may have stopped "
                f"running. Known meeting dates through {horizon.isoformat()}."
            )

    if today > horizon:
        return (
            f"[MACRO_SIGNAL_FOMC_CALENDAR] STALE: today ({today.isoformat()}) is past the "
            f"last known FOMC meeting date ({horizon.isoformat()}) - DFF rows from here "
            f"forward are being dropped from inter-meeting detection, not classified. "
            f"Run 'refresh-fomc-calendar' or check why its schedule stopped."
        )
    return None
