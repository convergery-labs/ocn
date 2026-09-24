"""macro_signal fetch orchestration, tracked via the same `runs` table
every other domain uses (GET /runs?domain=macro_signal) - explicit
decision to keep run tracking consistent across domains (see
fetch_macro_signals_cmd's own docstring history) rather than a
parallel, domain-specific tracking table.

Deliberately NOT routed through create_run_record/run_pipeline
(controllers/run.py) - that path assumes an article-shaped domain
registered in the `domains` table (ownership checks, days_back/focus/
model cache-hit matching, article fetch/filter/store) which
macro_signal has none of. This module calls create_run/complete_run/
fail_run directly instead - the same three functions every other
domain's run lifecycle bottoms out on, just without the article-domain
machinery layered on top that doesn't apply here.
"""
from __future__ import annotations

import logging
from datetime import datetime

from macro_signal_fetch import FETCH_LOOKBACK_DAYS, INCREMENTAL_LOOKBACK_DAYS, fetch_all_macro_signals
from models.macro_observations import insert_macro_observations
from models.runs import complete_run, create_run, fail_run

logger = logging.getLogger(__name__)

MACRO_SIGNAL_DOMAIN = "macro_signal"
_RUN_MODEL = "none"  # no LLM call in this fetch - matches the dead-column convention every other domain's run already uses (see controllers/run.py's own _RUN_MODEL comment)


def create_macro_fetch_run(*, incremental: bool) -> int:
    """Creates a runs row for a macro_signal fetch and returns its id.
    days_back is repurposed honestly here - it's not article recency,
    it's genuinely how far back THIS run looked
    (INCREMENTAL_LOOKBACK_DAYS or FETCH_LOOKBACK_DAYS), which is exactly
    what that column is for on every other domain's row too."""
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    days_back = INCREMENTAL_LOOKBACK_DAYS if incremental else FETCH_LOOKBACK_DAYS
    return create_run(
        name=f"{MACRO_SIGNAL_DOMAIN}_{timestamp}",
        domain=MACRO_SIGNAL_DOMAIN,
        days_back=days_back,
        max_articles=None,
        focus=None,
        model=_RUN_MODEL,
    )


def run_macro_fetch(run_id: int, fred_api_key: str, *, incremental: bool) -> None:
    """Runs fetch_all_macro_signals to completion and marks the run row
    completed/failed - the actual work, meant to run in a background
    task or thread (this function itself blocks synchronously for the
    duration of the real FRED/Treasury HTTP calls, same as the CLI
    command it mirrors)."""
    logger.info(
        "[MACRO_FETCH] run_id=%d starting (incremental=%s)", run_id, incremental,
    )
    try:
        observations = fetch_all_macro_signals(fred_api_key, incremental=incremental)
        count = insert_macro_observations(observations)
    except Exception as exc:
        logger.exception("[MACRO_FETCH] run_id=%d failed", run_id)
        fail_run(run_id, str(exc)[:500])
        return
    complete_run(run_id, count)
    logger.info("[MACRO_FETCH] run_id=%d complete: %d observations upserted", run_id, count)
