"""Orchestration - fetch articles from news-retrieval, classify via LLM, persist."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import config
from adapters.news_client import (
    NewsRetrievalError,
    fetch_latest_run,
    get_article,
    get_macro_observations,
    get_run_articles,
    list_completed_runs,
    poll_run_until_done,
    trigger_macro_fetch,
    trigger_run,
)
from models.geopolitical_signal_companies import (
    get_companies_for_name_matching,
    get_tickers_for_categories,
)
from models.jobs import (
    count_geopolitical_signal_stage_b_calls_today,
    count_geopolitical_signal_stage_c_calls_today,
    create_job,
    get_completed_job_for_run,
    get_existing_geopolitical_signal_article_ids,
    get_existing_korea_signal_source_ids,
    get_existing_macro_signal_source_ids,
    get_existing_taiwan_source_ids,
    get_taiwan_revenue_rows_for_periods,
    get_ungraded_geopolitical_signal_tagged_articles,
    get_untagged_geopolitical_signal_high_articles,
    get_waiting_geopolitical_signal_articles,
    insert_geopolitical_signal_classification,
    insert_korea_signal_classification,
    insert_macro_signal_event,
    insert_taiwan_signal_classification,
    list_all_results,
    list_macro_signal_events_for_confirmation_recheck,
    mark_macro_signal_event_suppressed,
    update_geopolitical_signal_classification,
    update_geopolitical_signal_stage_c_tags,
    update_geopolitical_signal_stage_d_grade,
    update_job_status,
    update_taiwan_revenue_rank,
)
from pipeline.classifier import has_usable_body
from pipeline.dispatch import get_domain_config, known_domains
from pipeline.geopolitical_signal_classifier import classify_geopolitical_signal_stage_a
from pipeline.geopolitical_signal_layer1 import find_direct_company_matches
from pipeline.geopolitical_signal_layer2 import classify_geopolitical_signal_tags
from pipeline.geopolitical_signal_overrides import apply_overrides
from pipeline.geopolitical_signal_stage_b import (
    classify_geopolitical_signal_headline,
    load_stage_b_prompt,
)
from pipeline.geopolitical_signal_stage_d import grade_geopolitical_signal_article
from pipeline.korea_signal_classifier import classify_korea_signal_batch
from pipeline.korea_signal_summary import generate_korea_signal_summary
from pipeline.korea_ticker_universe import KOREA_TICKER_UNIVERSE
from pipeline.macro_signal_collapse import collapse_events
from pipeline.macro_signal_confirmation import check_confirmation_reversal
from pipeline.macro_signal_fedtarmd import compute_sep_median_shift_bp
from pipeline.macro_signal_fomc_calendar import (
    calendar_staleness_warning,
    is_scheduled_fomc_date,
    is_within_known_calendar_horizon,
    refresh_fomc_meeting_dates,
)
from pipeline.macro_signal_frequency import CONFIRMATION_REVERSAL_ELIGIBLE
from pipeline.macro_signal_fetch_universe import MACRO_SERIES_TO_RELEASE_ID
from pipeline.macro_signal_interpret import interpret_events_batch
from pipeline.macro_signal_suppress import (
    apply_collinear_suppression,
    apply_derived_suppression,
    from_tier_result,
)
from pipeline.macro_signal_thresholds import (
    Channel,
    EXCLUDED_FROM_TIERING,
    SeriesMove,
    THRESHOLDS,
    Tier,
    tier_series_move,
)
from pipeline.macro_signal_zscore import compute_daily_changes, compute_series_zscores
from pipeline.taiwan_signal_classifier import classify_taiwan_signal_batch

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=config.CLASSIFY_CONCURRENCY)


async def resolve_news_run_id(
    domain: str,
    run_id: int | None,
    days_back: int,
    use_latest_run: bool,
) -> int:
    """Resolve which news-retrieval run to classify against."""
    if run_id is not None:
        await poll_run_until_done(run_id)
        return run_id
    if use_latest_run:
        existing = await fetch_latest_run(domain)
        if existing is not None:
            return existing
    resolved = await trigger_run(domain, days_back)
    await poll_run_until_done(resolved)
    return resolved


async def submit_run(
    domain: str,
    run_id: int | None,
    days_back: int,
    use_latest_run: bool,
    force: bool,
) -> tuple[int, int, bool]:
    """Resolve news_run_id, check cache, create job if needed.

    Returns (job_id, news_run_id, cached) where cached=True means an existing
    completed job was found and no new classification run is needed.
    """
    news_run_id = await resolve_news_run_id(domain, run_id, days_back, use_latest_run)
    if not force:
        existing = get_completed_job_for_run(news_run_id)
        if existing:
            return int(existing["id"]), news_run_id, True
    job_id = create_job(domain=domain, news_run_id=news_run_id)
    return job_id, news_run_id, False


def _is_period_in_active_filing_window(period_gregorian: str) -> bool:
    """A revenue period is only re-ranked against newly-arrived stragglers
    while it's the current or previous calendar month (UTC) - TWSE/TPEx
    monthly filings land within roughly the first 2-3 weeks after
    month-end, so anything older than that is treated as closed: no more
    re-ranking, no more update_taiwan_revenue_rank calls for it, ever.

    This bounds how long a stored row can change after the fact to a
    known, short window, rather than every row being mutable forever -
    the tradeoff decided over rank correctness vs. mutable history: fix
    the field size while filings are still trickling in for a period, but
    don't reopen a period that's long since settled.
    """
    try:
        period = datetime.strptime(period_gregorian, "%Y-%m").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    today = datetime.now(timezone.utc)
    months_diff = (today.year - period.year) * 12 + (today.month - period.month)
    return 0 <= months_diff <= 1


async def run_taiwan_signal_classification(job_id: int, from_date: str, to_date: str) -> None:
    """Classify taiwan_market_signal items across ALL of news-retrieval's
    completed runs in [from_date, to_date] - not just the latest run.

    news-retrieval polls this domain every 30 minutes, so a single day can
    have ~30 separate completed runs; fetch_latest_run/get_run_articles
    (built for the single-run news/sec_filing paths) would
    silently see only the most recent one. This function instead lists
    every completed run in the window and pools their articles before
    classifying, so a twice-daily pass sees the full day's fetched data.

    Only classifies items not already classified - checked via
    get_existing_taiwan_source_ids against the (ticker+period or
    ticker+timestamp) source_id classify_taiwan_signal_batch derives, not
    against article id, since the same underlying fact can legitimately
    appear in multiple news-retrieval runs (re-fetched, not yet superseded)
    and must still only be classified once.

    Revenue ranking is period-scoped, not just today's-batch-scoped: for
    every mops_revenue period present in today's pooled articles, this
    also pulls the already-stored rows for that period (if it's still in
    the active filing window - see _is_period_in_active_filing_window) as
    read-only ranking context, so a late-arriving filing gets ranked
    against the true known field instead of just itself. Any already-
    stored row whose rank/signal changes as a result is updated in place
    via update_taiwan_revenue_rank - see that function and
    rank_revenue_by_yoy's docstrings for why this is the one place
    taiwan_market_signal data is allowed to change after insert.
    """
    update_job_status(job_id, "running")
    try:
        run_ids = await list_completed_runs(
            config.TAIWAN_SIGNAL_DOMAIN, from_date, to_date,
        )
        all_articles: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for run_id in run_ids:
            for article in await get_run_articles(run_id):
                url = article.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(article)
    except NewsRetrievalError:
        logger.exception(
            "Failed to fetch taiwan_market_signal articles for job %d", job_id,
        )
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    if not all_articles:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    revenue_periods = {
        a["metadata"]["period_gregorian"]
        for a in all_articles
        if (a.get("metadata") or {}).get("source_category") == "mops_revenue"
        and a["metadata"].get("period_gregorian")
    }
    active_periods = [p for p in revenue_periods if _is_period_in_active_filing_window(p)]
    revenue_context = get_taiwan_revenue_rows_for_periods(active_periods)
    # get_taiwan_revenue_rows_for_periods returns {id, source_id, metadata}
    # rows shaped for the DB, not news-retrieval's article shape -
    # rank_revenue_by_yoy only ever reads/writes article["metadata"], so a
    # thin wrapper is enough; "id" being present is how it tells a context
    # row apart from a freshly-fetched article (see its docstring).
    context_wrapped = [
        {"id": r["id"], "source_id": r["source_id"], "metadata": r["metadata"]}
        for r in revenue_context
    ]

    # Rank/classify/translate needs the FULL pooled set together (ranking
    # spans all tickers for a period), so this runs before the
    # already-classified filter below - filtering first would rank against
    # a partial set and produce wrong ranks, same reasoning as
    # news-retrieval's original per-poll ranking gap.
    classified, changed_context = classify_taiwan_signal_batch(
        all_articles, revenue_context=context_wrapped,
    )

    candidate_source_ids = [c["result"]["source_id"] for c in classified]
    already_done = get_existing_taiwan_source_ids(candidate_source_ids)
    to_insert = [c for c in classified if c["result"]["source_id"] not in already_done]

    update_job_status(job_id, "running", article_count=len(to_insert))

    inserted = 0
    for c in to_insert:
        try:
            insert_taiwan_signal_classification(job_id, c["article"], c["result"])
            inserted += 1
        except Exception:
            logger.exception(
                "Failed to insert taiwan_market_signal classification for"
                " source_id=%s (job %d)",
                c["result"]["source_id"], job_id,
            )

    revised = 0
    for row in changed_context:
        meta = row["metadata"]
        try:
            update_taiwan_revenue_rank(
                row["source_id"],
                revenue_rank_signal=meta["revenue_rank_signal"],
                signal_reason=meta["revenue_rank_reason"],
                metadata=meta,
            )
            revised += 1
        except Exception:
            logger.exception(
                "Failed to update revised taiwan_market_signal rank for"
                " source_id=%s (job %d)",
                row["source_id"], job_id,
            )

    logger.info(
        "[TAIWAN_SIGNAL] job=%d runs=%d pooled_articles=%d classified=%d"
        " already_done=%d inserted=%d revenue_context=%d revised=%d",
        job_id, len(run_ids), len(all_articles), len(classified),
        len(already_done), inserted, len(context_wrapped), revised,
    )
    update_job_status(job_id, "completed", article_count=inserted, set_completed_at=True)


# DFF and FEDTARMD need inputs (inter-meeting date detection, SEP median
# shift) that aren't derivable via the generic z-score/tier path every
# other series uses - the spec documents these as genuinely special
# cases (an emergency Fed move date-matched against the FOMC calendar; a
# quarterly dot-plot comparison against the PRIOR SEP release, not a
# rolling window). Both are handled by their own tiering branches below
# (_tier_dff / _tier_fedtarmd), driven by the real FOMC calendar
# (fomc_meeting_dates table) and news-retrieval's per-(release,
# target_year) FEDTARMD rows, respectively - not skipped.
_GENERIC_TIER_SKIP_SERIES = frozenset({"DFF", "FEDTARMD"})


async def run_macro_signal_pipeline(job_id: int, from_date: str, to_date: str) -> None:
    """Runs the Macro Signal Backbone's deterministic core (Z-SCORE ->
    TIER -> SUPPRESS -> COLLAPSE) plus INTERPRET, end to end, for every
    tracked series with data in news-retrieval's macro_observations table.

    Pulls the FULL z-score window (config.MACRO_SIGNAL_ZSCORE_WINDOW_DAYS,
    default 730 days) per series on every run rather than maintaining an
    incremental watermark - simpler, and 46 series x ~2 years is a small
    enough pull that re-fetching daily isn't a real cost (see project
    plan history for this tradeoff).

    from_date/to_date bound which DATES' events get evaluated and
    persisted this run (typically "yesterday" for a daily scheduled
    run) - they do NOT bound how much history is pulled for z-score
    computation, which always goes back the full window regardless.

    DFEDTARU is fetched (news-retrieval stores it) but never tiered here
    - it's excluded from tiering per the spec, used only as a context
    field (dfedtaru_ctx_bp) attached to same-date events. Not yet wired
    into the interpret payload in this first pass - a real but narrow
    gap, tracked separately from the DFF/FEDTARMD wiring below.
    """
    update_job_status(job_id, "running")

    from datetime import date as _date, timedelta as _timedelta

    # Surfaces in ordinary operational logs on every run, well ahead of
    # the horizon guard actually dropping rows - see
    # macro_signal_fomc_calendar.calendar_staleness_warning's own
    # docstring for why this can't just be a one-time manual check.
    staleness_warning = calendar_staleness_warning(_date.today())
    if staleness_warning:
        logger.warning(staleness_warning)

    try:
        to_dt = _date.fromisoformat(to_date)
        window_start = to_dt - _timedelta(days=config.MACRO_SIGNAL_ZSCORE_WINDOW_DAYS + 30)
        all_observations = await get_macro_observations(
            from_date=window_start.isoformat(), to_date=to_date,
        )
        # FEDTARMD's observation_date is the PROJECTED TARGET YEAR (e.g.
        # 2029-01-01), not the real event date (the SEP release itself,
        # stored separately as vintage) - see macro_signal_fedtarmd.py's
        # own docstring. A target year can be several years past
        # `to_date`, so the bounded pull above silently excludes rows
        # for a release that itself happened well within window - e.g.
        # the 2026-09-16 release's own 2029 projection falls outside any
        # to_date<2029 bound despite the release being current. Fetched
        # separately, unbounded by observation_date (bounded only by
        # series), and merged in below.
        fedtarmd_observations = await get_macro_observations(series_ids=["FEDTARMD"])
    except NewsRetrievalError:
        logger.exception("Failed to fetch macro observations for job %d", job_id)
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    all_observations = [o for o in all_observations if o["series_id"] != "FEDTARMD"] + fedtarmd_observations

    if not all_observations:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    # CONFIRMED LIVE: news-retrieval's /macro/observations JSON response
    # serializes observation_date as an ISO string (FastAPI's default
    # date->JSON encoding) - it does NOT come back as a Python date
    # object the way it is inside news-retrieval's own Postgres reads.
    # Re-parse here, once, at the HTTP boundary, so every downstream
    # module (macro_signal_zscore's date arithmetic, tiered_by_date's
    # dict keys, etc.) can rely on a real date object without each
    # having to guard against a string.
    for obs in all_observations:
        if isinstance(obs.get("observation_date"), str):
            obs["observation_date"] = _date.fromisoformat(obs["observation_date"])
        if isinstance(obs.get("vintage"), str):
            obs["vintage"] = _date.fromisoformat(obs["vintage"])

    by_series: dict[str, list[dict[str, Any]]] = {}
    for obs in all_observations:
        by_series.setdefault(obs["series_id"], []).append(obs)

    from_dt = _date.fromisoformat(from_date)

    # --- Z-SCORE + TIER ---
    tiered_by_date: dict[Any, dict[str, Any]] = {}  # date -> {series_id: SuppressibleResult}
    for series_id, observations in by_series.items():
        if series_id in EXCLUDED_FROM_TIERING or series_id in _GENERIC_TIER_SKIP_SERIES:
            continue
        if series_id not in THRESHOLDS:
            continue  # tracked in news-retrieval's universe but not yet wired into THRESHOLDS
        zscores = compute_series_zscores(observations)
        sorted_obs_dates = sorted(o["observation_date"] for o in observations if o.get("value") is not None)
        for obs_date, (change_bp, z) in zscores.items():
            if not (from_dt <= obs_date <= to_dt):
                continue
            move = SeriesMove(series_id, d1d_bp=change_bp, z=z)
            tier_result = tier_series_move(move)
            obs_for_date = next((o for o in observations if o["observation_date"] == obs_date), None)
            # Real ask (frontend ticket, 2026-09-25, job 262): prior_value
            # populated for every series, not derived by the caller from
            # value - move_bp/100 - the immediately preceding real
            # observation in this series' own history, same day used to
            # compute change_bp above (compute_daily_changes.py).
            prior_idx = sorted_obs_dates.index(obs_date) - 1 if obs_date in sorted_obs_dates else -1
            prior_obs_date = sorted_obs_dates[prior_idx] if prior_idx >= 0 else None
            prior_obs = next((o for o in observations if o["observation_date"] == prior_obs_date), None) if prior_obs_date else None
            tiered_by_date.setdefault(obs_date, {})[series_id] = from_tier_result(
                tier_result,
                value=obs_for_date["value"] if obs_for_date else None,
                move_bp=change_bp,
                prior_value=prior_obs["value"] if prior_obs else None,
                source=obs_for_date.get("source") if obs_for_date else None,
                knowledge_time_confidence=obs_for_date.get("knowledge_time_confidence") if obs_for_date else None,
            )

    # --- DFF: inter-meeting move detection (spec's own z-gate exception) ---
    # DFF's own observation_date is the daily rate itself - unlike
    # DFEDTARU (the target UPPER BOUND, whose value changes land on the
    # calendar day AFTER the actual meeting - see
    # macro_signal_fomc_calendar.is_scheduled_fomc_date's own docstring
    # for the confirmed +1-day offset), DFF (the daily EFFECTIVE rate)
    # drifts continuously and a real target move shows up as a large
    # jump on the same +1-day-after-meeting date DFEDTARU uses - so the
    # same offset applies here, checked against the real, DB-backed FOMC
    # calendar (fomc_meeting_dates table).
    if "DFF" in by_series:
        dff_observations = by_series["DFF"]
        dff_zscores = compute_series_zscores(dff_observations)
        dff_sorted_obs_dates = sorted(o["observation_date"] for o in dff_observations if o.get("value") is not None)
        for obs_date, (change_bp, z) in dff_zscores.items():
            if not (from_dt <= obs_date <= to_dt):
                continue
            if not is_within_known_calendar_horizon(obs_date):
                logger.warning(
                    "[MACRO_SIGNAL] DFF %s is past the known FOMC calendar horizon - "
                    "cannot determine inter-meeting status, skipping this date's DFF tiering",
                    obs_date,
                )
                continue
            # CONFIRMED LIVE (2026-09-24 real 30-day classify run):
            # is_inter_meeting_date must NOT be "just not a scheduled
            # date" - that flagged every quiet, unchanged day between
            # meetings as an inter-meeting MOVE (change_bp==0, still
            # fired the no-gate HIGH path in _dff_rule), producing 4
            # consecutive days of fabricated HIGH events off a flat
            # rate. An inter-meeting move requires a REAL change on a
            # non-scheduled date - both conditions, not one.
            move = SeriesMove(
                "DFF", d1d_bp=change_bp, z=z,
                is_inter_meeting_date=(change_bp != 0 and not is_scheduled_fomc_date(obs_date)),
            )
            tier_result = tier_series_move(move)
            dff_obs_for_date = next((o for o in dff_observations if o["observation_date"] == obs_date), None)
            dff_prior_idx = dff_sorted_obs_dates.index(obs_date) - 1 if obs_date in dff_sorted_obs_dates else -1
            dff_prior_obs_date = dff_sorted_obs_dates[dff_prior_idx] if dff_prior_idx >= 0 else None
            dff_prior_obs = next((o for o in dff_observations if o["observation_date"] == dff_prior_obs_date), None) if dff_prior_obs_date else None
            tiered_by_date.setdefault(obs_date, {})["DFF"] = from_tier_result(
                tier_result,
                value=dff_obs_for_date["value"] if dff_obs_for_date else None,
                move_bp=change_bp,
                prior_value=dff_prior_obs["value"] if dff_prior_obs else None,
                source=dff_obs_for_date.get("source") if dff_obs_for_date else None,
                knowledge_time_confidence=dff_obs_for_date.get("knowledge_time_confidence") if dff_obs_for_date else None,
            )

    # --- FEDTARMD: SEP median shift (spec's own no-z-gate exception) ---
    # news-retrieval stores one row per (SEP release, projected target
    # year) - see macro_signal_fedtarmd.py's own docstring. Tier once
    # per real SEP release (vintage), keyed by the release date itself
    # (not a projection-year observation_date, which isn't a real event
    # date) so downstream SUPPRESS/COLLAPSE treat it the same as every
    # other series' obs_date-keyed dict.
    if "FEDTARMD" in by_series:
        fedtarmd_observations = by_series["FEDTARMD"]
        release_dates = sorted({o["vintage"] for o in fedtarmd_observations if o.get("vintage")})
        for release_date in release_dates:
            if not (from_dt <= release_date <= to_dt):
                continue
            sep_shift = compute_sep_median_shift_bp(fedtarmd_observations, release_date)
            move = SeriesMove("FEDTARMD", sep_median_shift_bp=sep_shift.shift_bp if sep_shift else None)
            tier_result = tier_series_move(move)
            representative_obs = next(
                (o for o in fedtarmd_observations if o.get("vintage") == release_date),
                None,
            )
            tiered_by_date.setdefault(release_date, {})["FEDTARMD"] = from_tier_result(
                tier_result,
                value=representative_obs["value"] if representative_obs else None,
                move_bp=sep_shift.shift_bp if sep_shift else None,
                target_year=sep_shift.target_year if sep_shift else None,
                prior_value=str(sep_shift.prior_value) if sep_shift else None,
                source=representative_obs.get("source") if representative_obs else None,
                knowledge_time_confidence=representative_obs.get("knowledge_time_confidence") if representative_obs else None,
            )

    # --- SUPPRESS (A then B) ---
    for obs_date, results in tiered_by_date.items():
        apply_derived_suppression(results)
        apply_collinear_suppression(results)

    # --- COLLAPSE ---
    release_id_of = {sid: MACRO_SERIES_TO_RELEASE_ID.get(sid, -1) for sid in by_series}
    all_events = []
    for obs_date, results in tiered_by_date.items():
        survivors = [r for r in results.values() if r.tier != Tier.NOISE]
        if not survivors:
            continue
        knowledge_time_of = {sid: obs_date for sid in results}
        events = collapse_events(survivors, release_id_of, knowledge_time_of)
        all_events.extend(events)

    # --- Persist suppressed/NOISE rows for audit (never deleted, per spec) ---
    audit_candidate_ids = []
    audit_rows = []
    for obs_date, results in tiered_by_date.items():
        for series_id, r in results.items():
            if r.suppressed_by is not None or r.tier == Tier.NOISE:
                source_id = f"{series_id}-{obs_date}"
                audit_candidate_ids.append(source_id)
                audit_rows.append({
                    "series_id": series_id, "observation_date": obs_date,
                    "tier": r.tier.value, "z_score": r.z_score,
                    "suppressed_by": r.suppressed_by, "knowledge_time": obs_date,
                    "source": r.source, "knowledge_time_confidence": r.knowledge_time_confidence,
                })
    already_audited = get_existing_macro_signal_source_ids(audit_candidate_ids)
    audited = 0
    for row in audit_rows:
        source_id = f"{row['series_id']}-{row['observation_date']}"
        if source_id in already_audited:
            continue
        try:
            insert_macro_signal_event(job_id, row, None)
            audited += 1
        except Exception:
            logger.exception("Failed to insert macro_signal audit row for %s (job %d)", source_id, job_id)

    # DFEDTARU context (spec section 7: excluded from tiering entirely,
    # but its own current level is real grounding context for a
    # policy_path event - "the funds rate target is currently 4.00-
    # 4.25%" - not itself a signal). {date: value} for O(1) lookup below;
    # value is the target UPPER BOUND in percent, converted to bp at
    # attach time to match every other series' native unit convention
    # in this pipeline.
    dfedtaru_by_date: dict[Any, float] = {
        o["observation_date"]: float(o["value"])
        for o in by_series.get("DFEDTARU", []) if o.get("value") is not None
    }
    dfedtaru_dates_sorted = sorted(dfedtaru_by_date)

    def _dfedtaru_ctx_bp(as_of: Any) -> float | None:
        """Most recent DFEDTARU value on or before `as_of` (its own
        daily series can lag a same-day event by the market-close
        knowledge_time convention every daily series uses - looking
        backward for the nearest known value is always safe here,
        this is context, not a timed observation)."""
        candidates = [d for d in dfedtaru_dates_sorted if d <= as_of]
        if not candidates:
            return None
        return dfedtaru_by_date[candidates[-1]] * 100

    # --- INTERPRET + persist survivors ---
    interpret_payloads = []
    for event in all_events:
        payload: dict[str, Any] = {
            "release_id": event.release_id,
            "knowledge_time": event.knowledge_time.isoformat() if hasattr(event.knowledge_time, "isoformat") else str(event.knowledge_time),
            "channel": event.channel.value,
            "members": [
                {
                    "series_id": m.series_id, "value": m.value,
                    # No rounding/truncation - move_bp is exact as of the
                    # Decimal fix in macro_signal_zscore.py/
                    # macro_signal_fedtarmd.py (real frontend ticket,
                    # 2026-09-25: a prior truncation step here made float
                    # noise WORSE, e.g. 4.999999999999996 truncated to
                    # 4.99 instead of the real exact value 5).
                    "move_bp": m.move_bp,
                    "target_year": m.target_year, "prior_value": m.prior_value,
                    "z_score": m.z_score, "tier": m.tier.value,
                    "classification_basis": m.reason,
                    "classification_reason": m.plain_reason,
                }
                for m in event.members
            ],
        }
        if event.channel == Channel.POLICY_PATH:
            ctx_bp = _dfedtaru_ctx_bp(event.knowledge_time)
            if ctx_bp is not None:
                payload["dfedtaru_ctx_bp"] = ctx_bp
        interpret_payloads.append(payload)

    interpreted = interpret_events_batch(interpret_payloads) if interpret_payloads else []

    # event.members (real SuppressibleResult objects, not yet flattened to
    # the plain dicts interpret_payloads carries) is where source/
    # knowledge_time_confidence still live - looked up back by
    # (release_id, channel, knowledge_time) below since interpret_payloads
    # and all_events share index order but interpreted's own order can
    # differ after the ThreadPoolExecutor fan-out.
    members_by_event_key = {
        (e.release_id, e.channel.value, e.knowledge_time.isoformat() if hasattr(e.knowledge_time, "isoformat") else str(e.knowledge_time)): e.members
        for e in all_events
    }

    inserted = 0
    for item in interpreted:
        event_payload = item["event"]
        interpretation = item["interpretation"]
        event_key = (event_payload["release_id"], event_payload["channel"], event_payload["knowledge_time"])
        real_members = members_by_event_key.get(event_key, [])
        macro_event = {
            "release_id": event_payload["release_id"],
            "channel": event_payload["channel"],
            "knowledge_time": event_payload["knowledge_time"],
            "tier": max((m["tier"] for m in event_payload["members"]), key=lambda t: t == "HIGH"),
            "member_series": [m["series_id"] for m in event_payload["members"]],
            "z_scores": {m["series_id"]: m["z_score"] for m in event_payload["members"]},
            # move_bp/target_year fill the exact gap a frontend hit live:
            # z_scores.FEDTARMD is always null (its rule is a no-z-gate
            # SEP-median-shift exception, not a z-score threshold - see
            # macro_signal_thresholds._fedtarmd_rule), so without these
            # there was no field anywhere saying WHAT number made it HIGH
            # or WHICH projected year "the medium-run fed funds target"
            # meant. Populated for every series (not just FEDTARMD) since
            # any member could in principle need the same Current/Prior/
            # Change display; target_year is None for every series except
            # FEDTARMD, where it is never None on an interpreted event.
            "move_bp": {m["series_id"]: m["move_bp"] for m in event_payload["members"]},
            "target_years": {
                m["series_id"]: m["target_year"]
                for m in event_payload["members"] if m.get("target_year") is not None
            },
            # Real ask (frontend ticket, 2026-09-25, item 7 - "all numbers
            # must be correct and consistent"): a UI's Current/Prior/
            # Change display needs the actual two readings move_bp was
            # computed from, not just the delta. current_values is
            # `value` (the current reading); prior_values is the
            # immediately preceding real observation for every standard
            # series, or the prior SEP release's own value for FEDTARMD
            # (see SuppressibleResult.prior_value's own docstring) -
            # populated for every series in member_series, not just
            # FEDTARMD (CONFIRMED LIVE a frontend found it missing on 28
            # of 29 events - it was only ever wired for FEDTARMD before
            # this fix). Both are strings, matching `value`'s own
            # convention, not bare floats.
            "current_values": {m["series_id"]: m["value"] for m in event_payload["members"]},
            "prior_values": {
                m["series_id"]: m["prior_value"]
                for m in event_payload["members"] if m.get("prior_value") is not None
            },
            # Real ask (frontend ticket, 2026-09-25): a FEDTARMD event is
            # HIGH with z_scores.FEDTARMD always null (its rule gates on
            # move_bp, not a z-score - see _fedtarmd_rule), and move_bp/
            # target_years alone don't say WHICH RULE decided the tier.
            # classification_basis is TierResult.reason verbatim (e.g.
            # "sep_median_shift_50.0bp_ge_25_no_zgate") - already computed
            # at TIER time for every series, just never persisted before.
            "classification_basis": {
                m["series_id"]: m["classification_basis"] for m in event_payload["members"]
            },
            # Real ask (frontend ticket, 2026-09-25): classification_basis
            # (above) is a machine-readable tag, not something the
            # frontend can show verbatim in "Why did AlphaStreet flag
            # it?" without parsing it. classification_reason is a real
            # plain-English sentence per series, written inline by the
            # exact rule branch that fired (TierResult.plain_reason - see
            # macro_signal_thresholds.py's own rule functions), always
            # naming the tier, the real threshold, and the z-score (or
            # "no z-score check" when the rule has none) - never derived
            # by parsing classification_basis, so it can't drift out of
            # sync with the logic that actually ran. classification_basis
            # itself is kept as-is for debugging, per explicit request.
            "classification_reason": {
                m["series_id"]: m["classification_reason"]
                for m in event_payload["members"] if m.get("classification_reason") is not None
            },
            # Deduplicated arrays, not a per-series map - the VALUE (which
            # source/confidence) is what matters here, and every member of
            # a collapsed event shares the same value in practice today,
            # but this stays a real array (not a single string) rather than
            # silently collapsing to one value if a genuinely mixed-source
            # event (e.g. a fred series collapsed alongside close_today_bal)
            # ever occurs - never guess, never quietly drop a real distinct
            # value, same principle as KnowledgeTimeDropped's own fail-loud
            # contract elsewhere in this pipeline.
            "sources": sorted({m.source for m in real_members if m.source}),
            "knowledge_time_confidences": sorted({m.knowledge_time_confidence for m in real_members if m.knowledge_time_confidence}),
        }
        # CONFIRMED LIVE: release_id alone is not a unique event key - some
        # release_ids are shared across channels (e.g. release_id=18 covers
        # both DFF/DFEDTARU's policy_path channel and DFII10/T10Y3M's
        # discount_rate channel, since COLLAPSE groups survivors by
        # (release_id, channel), not release_id alone). Without channel in
        # source_id, a second channel's real event on the same release+date
        # silently collided with an already-inserted event and was dropped
        # as a false "duplicate" - found live: a real DFF WEAK event on
        # 2026-09-17 was lost this way because release_id=18's
        # discount_rate event for the same date had already claimed
        # "18-2026-09-17".
        source_id = f"{macro_event['release_id']}-{macro_event['channel']}-{macro_event['knowledge_time']}"
        if source_id in get_existing_macro_signal_source_ids([source_id]):
            continue
        try:
            insert_macro_signal_event(job_id, macro_event, interpretation)
            inserted += 1
        except Exception:
            logger.exception("Failed to insert macro_signal event for source_id=%s (job %d)", source_id, job_id)

    logger.info(
        "[MACRO_SIGNAL] job=%d series=%d dates_evaluated=%d events_collapsed=%d"
        " interpreted=%d inserted=%d audited=%d",
        job_id, len(by_series), len(tiered_by_date), len(all_events),
        len(interpreted), inserted, audited,
    )
    update_job_status(job_id, "completed", article_count=inserted, set_completed_at=True)


async def run_macro_signal_full_chain(
    job_id: int, from_date: str, to_date: str, *, incremental: bool,
) -> None:
    """The full 'store the backfill, then classify' chain, as one
    agent_jobs-tracked background job: trigger news-retrieval's real
    macro fetch (POST /macro/fetch, itself tracked in news-retrieval's
    OWN runs table - GET /runs?domain=macro_signal) -> wait for it to
    complete -> refresh the FOMC calendar -> run the deterministic
    pipeline (Z-SCORE -> TIER -> SUPPRESS -> COLLAPSE -> INTERPRET) over
    [from_date, to_date].

    Two DIFFERENT run-tracking records are created by one call to this
    function - a real, deliberate consequence of macro_signal spanning
    two services that each track their own work in their own `runs`/
    `agent_jobs` table (see controllers.macro_run's own docstring in
    news-retrieval for why the fetch isn't tracked here instead). This
    function's own job_id (passed in, already created by the caller -
    routes/macro.py) is signal-detection-agent's job; the fetch's own
    run_id (returned by trigger_macro_fetch, logged below) is
    news-retrieval's - both are real, both queryable, neither
    fabricated to look unified.
    """
    update_job_status(job_id, "running")
    try:
        fetch_run_id = await trigger_macro_fetch(incremental=incremental)
        logger.info(
            "[MACRO_SIGNAL_CHAIN] job=%d triggered news-retrieval fetch run_id=%d (incremental=%s), waiting...",
            job_id, fetch_run_id, incremental,
        )
        await poll_run_until_done(fetch_run_id)
    except NewsRetrievalError:
        logger.exception("[MACRO_SIGNAL_CHAIN] job=%d news-retrieval fetch failed or timed out", job_id)
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    logger.info("[MACRO_SIGNAL_CHAIN] job=%d fetch complete, refreshing FOMC calendar...", job_id)
    try:
        await asyncio.to_thread(refresh_fomc_meeting_dates)
    except Exception:
        # A stale/unrefreshed calendar degrades DFF's inter-meeting
        # detection (calendar_staleness_warning inside
        # run_macro_signal_pipeline below will surface this in logs) but
        # does not block every other series' tiering - not fatal to the
        # whole chain, logged and continued rather than aborting a real
        # fetch+backfill over a calendar refresh hiccup.
        logger.exception("[MACRO_SIGNAL_CHAIN] job=%d FOMC calendar refresh failed - continuing anyway", job_id)

    logger.info("[MACRO_SIGNAL_CHAIN] job=%d running pipeline for [%s, %s]...", job_id, from_date, to_date)
    await run_macro_signal_pipeline(job_id, from_date, to_date)


async def run_macro_signal_confirmation_recheck(job_id: int, since_date: str) -> None:
    """Suppression mechanism C (spec section 5, Confirmation override):
    re-examines already-stored macro_signal rows for weekly/monthly
    series (CONFIRMATION_REVERSAL_ELIGIBLE - see
    macro_signal_frequency.py) and retroactively marks any whose move
    has since FULLY reversed at the next observation as suppressed,
    per check_confirmation_reversal's own definition of "fully
    reverses" (opposite sign, magnitude >= the original).

    Retroactive by nature - this is a SEPARATE pass from
    run_macro_signal_pipeline, not folded into it, because the
    confirming next observation usually does not exist yet at the time
    the original event was tiered/collapsed/interpreted (a monthly
    series' next print is up to ~4 weeks later). Safe to run daily:
    re-checking an event that has no new next-observation yet is a
    cheap no-op (see_next_change is None -> not reversed, per
    check_confirmation_reversal), and an already-suppressed row is
    excluded from the candidate query entirely.

    Only re-derives the ORIGINAL row's own change from a fresh
    observations pull (not from metadata.z_scores, which stores a
    z-score, not the raw native-unit change) - same compute_daily_
    changes function the main pipeline uses, so "the move" means the
    identical thing in both passes.
    """
    update_job_status(job_id, "running")
    eligible_series = sorted(CONFIRMATION_REVERSAL_ELIGIBLE)

    candidates = list_macro_signal_events_for_confirmation_recheck(eligible_series, since_date)
    if not candidates:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        logger.info("[MACRO_SIGNAL_RECHECK] job=%d no candidates since %s", job_id, since_date)
        return

    try:
        observations = await get_macro_observations(series_ids=eligible_series, from_date=since_date)
    except NewsRetrievalError:
        logger.exception("Failed to fetch macro observations for confirmation recheck job %d", job_id)
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    from datetime import date as _date
    for obs in observations:
        if isinstance(obs.get("observation_date"), str):
            obs["observation_date"] = _date.fromisoformat(obs["observation_date"])

    by_series: dict[str, list[dict[str, Any]]] = {}
    for obs in observations:
        by_series.setdefault(obs["series_id"], []).append(obs)
    changes_by_series = {sid: compute_daily_changes(obs_list) for sid, obs_list in by_series.items()}

    reversed_count = 0
    checked_count = 0
    for row in candidates:
        metadata = row["metadata"]
        row_date = row["published"].date() if hasattr(row["published"], "date") else row["published"]
        member_series = metadata.get("member_series") or (
            [metadata["series_id"]] if metadata.get("series_id") else []
        )
        eligible_members = [s for s in member_series if s in CONFIRMATION_REVERSAL_ELIGIBLE]
        if not eligible_members:
            continue

        any_reversed = False
        reversing_series = None
        for series_id in eligible_members:
            changes = changes_by_series.get(series_id, {})
            original_change = changes.get(row_date)
            if original_change is None:
                continue  # this row's own date isn't in the re-fetched window - can't recheck
            future_dates = sorted(d for d in changes if d > row_date)
            next_change = changes[future_dates[0]] if future_dates else None
            checked_count += 1
            result = check_confirmation_reversal(series_id, original_change, next_change)
            if result.reversed:
                any_reversed = True
                reversing_series = series_id
                break

        if any_reversed:
            rule = f"confirmation_reversal:{reversing_series}"
            try:
                updated = mark_macro_signal_event_suppressed(row["source_id"], rule)
                if updated:
                    reversed_count += 1
                    logger.info(
                        "[MACRO_SIGNAL_RECHECK] job=%d suppressed source_id=%s via %s",
                        job_id, row["source_id"], rule,
                    )
            except Exception:
                logger.exception(
                    "Failed to mark confirmation-reversed macro_signal row source_id=%s (job %d)",
                    row["source_id"], job_id,
                )

    logger.info(
        "[MACRO_SIGNAL_RECHECK] job=%d candidates=%d checked=%d reversed=%d",
        job_id, len(candidates), checked_count, reversed_count,
    )
    update_job_status(job_id, "completed", article_count=reversed_count, set_completed_at=True)


async def run_korea_signal_classification(job_id: int, from_date: str, to_date: str) -> None:
    """Classify korea_market_signal items across ALL of news-retrieval's
    completed runs in [from_date, to_date] - not just the latest run, same
    reasoning as run_taiwan_signal_classification (news-retrieval polls
    this domain every 4 hours, so a multi-day window or a slow day can
    still span more than one completed run).

    Simpler than the Taiwan controller: no revenue-context re-ranking step
    (see classify_korea_signal_batch's own docstring - no Korea signal
    type judges an article against a field of peers the way Taiwan's YoY
    ranking does), so this is pool -> classify -> dedup -> insert, no
    "changed_context" second return value or update_taiwan_revenue_rank
    equivalent.

    Only inserts items not already classified - checked via
    get_existing_korea_signal_source_ids against the source_id
    classify_korea_signal_batch derives (rcept_no for DART filings, the
    article's own url for S7 qualification_news), not against article id,
    for the same reason Taiwan's controller checks source_id instead of
    id: the same underlying fact can legitimately reappear across
    multiple news-retrieval runs before this job ever ran.
    """
    update_job_status(job_id, "running")
    try:
        run_ids = await list_completed_runs(
            config.KOREA_SIGNAL_DOMAIN, from_date, to_date,
        )
        all_articles: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for run_id in run_ids:
            for article in await get_run_articles(run_id):
                url = article.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(article)
    except NewsRetrievalError:
        logger.exception(
            "Failed to fetch korea_market_signal articles for job %d", job_id,
        )
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    if not all_articles:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    classified = classify_korea_signal_batch(all_articles, tracked_companies=KOREA_TICKER_UNIVERSE)

    candidate_source_ids = [c["result"]["source_id"] for c in classified if c["result"].get("source_id")]
    already_done = get_existing_korea_signal_source_ids(candidate_source_ids)
    to_insert = [
        c for c in classified
        if c["result"].get("source_id") not in already_done
    ]

    update_job_status(job_id, "running", article_count=len(to_insert))

    inserted = 0
    for c in to_insert:
        try:
            insert_korea_signal_classification(job_id, c["article"], c["result"])
            inserted += 1
        except Exception:
            logger.exception(
                "Failed to insert korea_market_signal classification for"
                " source_id=%s (job %d)",
                c["result"].get("source_id"), job_id,
            )

    logger.info(
        "[KOREA_SIGNAL] job=%d runs=%d pooled_articles=%d classified=%d"
        " already_done=%d inserted=%d",
        job_id, len(run_ids), len(all_articles), len(classified),
        len(already_done), inserted,
    )
    update_job_status(job_id, "completed", article_count=inserted, set_completed_at=True)


def generate_korea_signal_summary_for_date(date: str) -> str:
    """Spec Section 8.4: read today's (or ``date``'s) already-classified
    korea_market_signal rows from this service's own DB and generate the
    twice-daily trader summary text.

    Not async (unlike the run_* functions above) - list_all_results is a
    plain synchronous DB call (models/jobs.py, same psycopg2 connection
    every other model function in this service uses), and
    generate_korea_signal_summary itself is a synchronous urllib call
    (matching every other LLM call in this codebase's pipeline/*.py
    modules - none of them are async either). No news-retrieval fetch
    here at all, unlike run_korea_signal_classification - this only reads
    rows this service has ALREADY classified and inserted.

    Rows are sorted signal before weak_signal, then newest published
    first - see korea_signal_summary.py's own module docstring for why no
    numeric rank is fabricated here instead.

    ``date``: YYYY-MM-DD (UTC) - passed straight to list_all_results's
    published_from/published_to as a single-day window.
    """
    result = list_all_results(
        source_type=config.KOREA_SIGNAL_DOMAIN,
        published_from=date,
        published_to=date,
        limit=200,
    )
    rows = result["results"]

    # signal before weak_signal, newest published first within each group -
    # a stable sort by published-descending, then a stable partition by
    # signal_detection, achieves exactly that without a double-sort: the
    # partition preserves each group's own already-newest-first order
    # (list_all_results' own query already returns rows ORDER BY
    # effective_date DESC).
    signal_rows = [r for r in rows if r.get("signal_detection") == "signal"]
    weak_rows = [r for r in rows if r.get("signal_detection") == "weak_signal"]
    ordered_rows = signal_rows + weak_rows

    logger.info(
        "[KOREA_SIGNAL_SUMMARY] date=%s signal=%d weak_signal=%d",
        date, len(signal_rows), len(weak_rows),
    )
    return generate_korea_signal_summary(ordered_rows)


async def run_geopolitical_signal_stage_a(job_id: int, from_date: str, to_date: str) -> None:
    """Stage A only: pool all of news-retrieval's completed geopolitical_news
    runs in [from_date, to_date], apply the free rule-based filters, persist.

    Pools across every completed run in the window rather than just the
    latest (same reasoning as run_taiwan_signal_classification) - a single
    run isn't guaranteed to be "today's everything" for this domain either.

    Only classifies articles not already classified - checked via
    get_existing_geopolitical_signal_article_ids against article_id
    (Stage A rule 1, "already classified: skip"), unlike Taiwan's
    source_id-based check, since geopolitical_signal's natural key really
    is the news-retrieval article_id (no ticker+period/ticker+timestamp
    concept here). No model call anywhere in this function - see
    pipeline/geopolitical_signal_classifier.py's module docstring.
    """
    update_job_status(job_id, "running")
    try:
        run_ids = await list_completed_runs(
            config.GEOPOLITICAL_SIGNAL_DOMAIN, from_date, to_date,
        )
        all_articles: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for run_id in run_ids:
            for article in await get_run_articles(run_id):
                url = article.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(article)
    except NewsRetrievalError:
        logger.exception(
            "Failed to fetch geopolitical_news articles for job %d", job_id,
        )
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    if not all_articles:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    already_done = get_existing_geopolitical_signal_article_ids(
        [a["id"] for a in all_articles if a.get("id") is not None],
    )
    to_classify = [a for a in all_articles if a.get("id") not in already_done]

    update_job_status(job_id, "running", article_count=len(to_classify))

    outcome_counts: dict[str, int] = {"DROPPED": 0, "WEAK": 0, "WAITING": 0}
    inserted = 0
    for article in to_classify:
        result = classify_geopolitical_signal_stage_a(article)
        outcome_counts[result["outcome"]] = outcome_counts.get(result["outcome"], 0) + 1
        try:
            insert_geopolitical_signal_classification(job_id, article, result)
            inserted += 1
        except Exception:
            logger.exception(
                "Failed to insert geopolitical_signal Stage A result for"
                " article_id=%s (job %d)",
                article.get("id"), job_id,
            )

    logger.info(
        "[GEOPOLITICAL_SIGNAL_STAGE_A] job=%d runs=%d pooled_articles=%d"
        " already_done=%d classified=%d inserted=%d dropped=%d weak=%d waiting=%d",
        job_id, len(run_ids), len(all_articles), len(already_done),
        len(to_classify), inserted, outcome_counts["DROPPED"],
        outcome_counts["WEAK"], outcome_counts["WAITING"],
    )
    update_job_status(job_id, "completed", article_count=inserted, set_completed_at=True)


async def run_geopolitical_signal_stage_b(job_id: int) -> None:
    """Stage B: one Haiku-class HIGH/WEAK call per Stage A survivor
    (signal_detection='waiting'), update each row in place. Rows are
    classified concurrently (bounded by CLASSIFY_CONCURRENCY, the same
    thread pool the news domain and Stage C share), not one at a time.

    No fetch from news-retrieval here - Stage B's entire input is already
    sitting in agent_classifications from Stage A (get_waiting_geopolitical_
    signal_articles), so this never re-reads news-retrieval at all.

    Daily cap (config.GEOPOLITICAL_SIGNAL_STAGE_B_DAILY_CAP, default 1000)
    is a safety tripwire against a bug flooding the worklist, not a cost
    control (even a 10x normal day costs under $1 per the spec's own cost
    math) - once hit, remaining waiting rows are left untouched for the
    next run, never forced through and never dropped.
    """
    update_job_status(job_id, "running")

    waiting = get_waiting_geopolitical_signal_articles()
    if not waiting:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    already_today = count_geopolitical_signal_stage_b_calls_today()
    remaining_cap = max(0, config.GEOPOLITICAL_SIGNAL_STAGE_B_DAILY_CAP - already_today)
    to_classify = waiting[:remaining_cap]
    capped = len(waiting) - len(to_classify)

    update_job_status(job_id, "running", article_count=len(to_classify))

    system_prompt = load_stage_b_prompt()
    model = config.GEOPOLITICAL_SIGNAL_MODEL
    api_key = config.OPENAI_API_KEY
    base_url = config.OPENAI_BASE_URL
    timeout = config.OPENAI_TIMEOUT

    # Reuses the module-level _executor/CLASSIFY_CONCURRENCY that
    # run_agent_pipeline (news) and Stage C both share, rather than a
    # dedicated pool - same kind of blocking single-call HTTP classification,
    # no reason to double the thread pools in this process for it.
    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def classify_one(row: dict[str, Any]) -> str | None:
        """Classify + persist one row; returns its outcome, or None on failure."""
        async with semaphore:
            outcome = await loop.run_in_executor(
                _executor,
                lambda: classify_geopolitical_signal_headline(
                    row["title"] or "",
                    system_prompt=system_prompt,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    timeout=timeout,
                ),
            )
            try:
                update_geopolitical_signal_classification(row["id"], outcome=outcome)
                return outcome
            except Exception:
                logger.exception(
                    "Failed to update geopolitical_signal Stage B result for"
                    " row id=%s article_id=%s (job %d)",
                    row["id"], row.get("article_id"), job_id,
                )
                return None

    outcomes = await asyncio.gather(*[classify_one(row) for row in to_classify])
    outcome_counts: dict[str, int] = {"HIGH": 0, "WEAK": 0}
    updated = 0
    for outcome in outcomes:
        if outcome is not None:
            outcome_counts[outcome] += 1
            updated += 1

    logger.info(
        "[GEOPOLITICAL_SIGNAL_STAGE_B] job=%d waiting=%d already_today=%d"
        " capped=%d classified=%d updated=%d high=%d weak=%d",
        job_id, len(waiting), already_today, capped, len(to_classify),
        updated, outcome_counts["HIGH"], outcome_counts["WEAK"],
    )
    update_job_status(job_id, "completed", article_count=updated, set_completed_at=True)


async def run_geopolitical_signal_stage_c(job_id: int) -> None:
    """Stage C: tag every untagged HIGH article - channel, actors, assets,
    impacted_categories, one_line, impacted_companies_direct.

    Flow per article, matching the locked Stage C plan:
      GET /articles/{id} (body, best-effort) -> Layer 1 (free) -> Layer 2
      (1 model call) -> deterministic overrides (free) -> Layer 3 (free,
      cache read) -> update in place.
    Rows are classified concurrently (bounded by CLASSIFY_CONCURRENCY,
    same pool as Stage B and the news domain), not one at a time - each
    row's flow above runs as a single unit in the shared thread pool.

    Stage C's row data (title only) comes entirely from this table
    (get_untagged_geopolitical_signal_high_articles); body text is fetched
    per article from news-retrieval (get_article) so Layer 2 isn't judging
    off a headline alone - a terse headline often omits the specific
    goods/sector the prompt's own empty-impacted_categories rule requires.
    That fetch fails open to headline-only (None body) if the article has
    since expired from news-retrieval's 7-day geopolitical_news retention,
    or the request otherwise fails - a missing body must never drop or
    fail the row, same fail-open discipline as Layer 2's own model-call
    handling. Layer 1's company list is loaded ONCE for the whole run, not
    once per article (see get_companies_for_name_matching's docstring) -
    this was a deliberate fix during design review, not the naive
    per-article refetch the original plan implied.

    Daily cap (config.GEOPOLITICAL_SIGNAL_STAGE_C_DAILY_CAP, default 50) is
    a safety tripwire, same reasoning as Stage B's cap - once hit,
    remaining untagged rows are left untouched for the next run.
    """
    update_job_status(job_id, "running")

    untagged = get_untagged_geopolitical_signal_high_articles()
    if not untagged:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    already_today = count_geopolitical_signal_stage_c_calls_today()
    remaining_cap = max(0, config.GEOPOLITICAL_SIGNAL_STAGE_C_DAILY_CAP - already_today)
    to_classify = untagged[:remaining_cap]
    capped = len(untagged) - len(to_classify)

    update_job_status(job_id, "running", article_count=len(to_classify))

    companies = get_companies_for_name_matching()
    system_prompt = config.GEOPOLITICAL_SIGNAL_STAGE_C_PROMPT.read_text(encoding="utf-8")
    model = config.GEOPOLITICAL_SIGNAL_STAGE_C_MODEL
    api_key = config.OPENAI_API_KEY
    base_url = config.OPENAI_BASE_URL
    timeout = config.OPENAI_TIMEOUT

    # Runs each row's whole Layer1->Layer2->overrides->Layer3->DB-write body
    # as one executor job, not split across separate awaits - Layer 3's
    # get_tickers_for_categories is a blocking DB call, so splitting it out
    # into its own run_in_executor would still block the event loop for
    # nothing (no other awaitable work happens between it and the model
    # call). Reuses the same _executor/CLASSIFY_CONCURRENCY pool Stage B
    # and the news domain already share.
    def _tag_one_sync(row: dict[str, Any], body: str | None) -> dict[str, Any] | None:
        title = row["title"] or ""

        # Layer 1 - free, always kept regardless of what Layer 2 returns.
        direct_matches = find_direct_company_matches(title, companies)

        # Layer 2 - one model call; fail-open on any parse/shape failure.
        # body is None when news-retrieval's article already expired
        # (geopolitical_news is a 7-day retention domain) or the fetch
        # failed - classify_geopolitical_signal_tags degrades to
        # headline-only in that case rather than failing the row.
        layer2_result = classify_geopolitical_signal_tags(
            title,
            body=body,
            system_prompt=system_prompt,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

        # Deterministic overrides - only ever add categories.
        final_categories = apply_overrides(
            channel=layer2_result["channel"],
            actors=layer2_result["actors"],
            assets=layer2_result["assets"],
            impacted_categories=layer2_result["impacted_categories"],
        )

        # Layer 3 - free cache lookup, only for the categories actually
        # chosen. Already [{ticker, company_name, matched_categories}] -
        # one entry per ticker, not per ticker-category pair (see
        # get_tickers_for_categories' docstring).
        category_matches = get_tickers_for_categories(final_categories)

        tags = {
            "channel": layer2_result["channel"],
            "actors": layer2_result["actors"],
            "assets": layer2_result["assets"],
            "impacted_categories": final_categories or None,
            "impacted_companies_direct": direct_matches or None,
            "impacted_companies_by_category": category_matches or None,
            "one_line": layer2_result["one_line"],
        }
        try:
            update_geopolitical_signal_stage_c_tags(row["id"], tags=tags)
            return tags
        except Exception:
            logger.exception(
                "Failed to update geopolitical_signal Stage C tags for"
                " row id=%s article_id=%s (job %d)",
                row["id"], row.get("article_id"), job_id,
            )
            return None

    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def tag_one(row: dict[str, Any]) -> dict[str, Any] | None:
        async with semaphore:
            # get_article is already async (own httpx.AsyncClient per call,
            # same as Stage D's grade_one) - fetched here, before handing
            # off to the executor, so the blocking Layer1->Layer3 body
            # doesn't also have to manage an event loop. None (article
            # expired/404, or body missing/blank) degrades Layer 2 to
            # headline-only rather than failing the row.
            article = await get_article(row["article_id"])
            body = (article.get("body") or None) if article else None
            return await loop.run_in_executor(_executor, _tag_one_sync, row, body)

    results = await asyncio.gather(*[tag_one(row) for row in to_classify])
    updated = sum(1 for r in results if r is not None)

    logger.info(
        "[GEOPOLITICAL_SIGNAL_STAGE_C] job=%d untagged=%d already_today=%d"
        " capped=%d classified=%d updated=%d",
        job_id, len(untagged), already_today, capped, len(to_classify), updated,
    )
    update_job_status(job_id, "completed", article_count=updated, set_completed_at=True)


async def run_geopolitical_signal_stage_d(job_id: int) -> None:
    """Stage D: grade every Stage-C-tagged HIGH article into TOP/STRONG/
    STANDARD via three free checks (see pipeline/geopolitical_signal_
    stage_d.py's module docstring for the exact rules).

    No model call, no daily cap (unlike Stage B/C - there's no external
    API cost here to tripwire against). One news-retrieval call per
    article (GET /articles/{id}) to read metadata.also_reported_by, which
    only ever lives on the source article, never copied into this
    service's own rows. Fetches run concurrently (bounded by
    CLASSIFY_CONCURRENCY) via asyncio.gather - no thread pool needed since
    get_article is already async and grading itself does no I/O.
    """
    update_job_status(job_id, "running")

    ungraded = get_ungraded_geopolitical_signal_tagged_articles()
    if not ungraded:
        update_job_status(job_id, "completed", article_count=0, set_completed_at=True)
        return

    update_job_status(job_id, "running", article_count=len(ungraded))

    # get_article is already async (its own httpx.AsyncClient per call), and
    # grade_geopolitical_signal_article is pure/local (no I/O) - no thread
    # pool needed here, just gather the news-retrieval fetches behind the
    # same concurrency cap the other stages use.
    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)

    async def grade_one(row: dict[str, Any]) -> bool:
        async with semaphore:
            article = await get_article(row["article_id"])
            also_reported_by = (
                (article.get("metadata") or {}).get("also_reported_by") if article else None
            )

            grade_fields = grade_geopolitical_signal_article(
                url=row["url"],
                title=row["title"],
                also_reported_by=also_reported_by,
                impacted_companies_direct=row.get("impacted_companies_direct"),
            )

            try:
                update_geopolitical_signal_stage_d_grade(row["id"], grade_fields=grade_fields)
                return True
            except Exception:
                logger.exception(
                    "Failed to update geopolitical_signal Stage D grade for"
                    " row id=%s article_id=%s (job %d)",
                    row["id"], row.get("article_id"), job_id,
                )
                return False

    outcomes = await asyncio.gather(*[grade_one(row) for row in ungraded])
    graded = sum(outcomes)

    logger.info(
        "[GEOPOLITICAL_SIGNAL_STAGE_D] job=%d ungraded=%d graded=%d",
        job_id, len(ungraded), graded,
    )
    update_job_status(job_id, "completed", article_count=graded, set_completed_at=True)


async def run_agent_pipeline(job_id: int, domain: str, news_run_id: int, limit: int | None = None) -> None:
    """Background task: fetch → classify → persist.

    Routing is entirely dispatch.get_domain_config(domain) - sec_filing and
    taiwan_market_signal never reach this function (they have their own
    entry points: controllers/filing_run.py, run_taiwan_signal_classification
    above), so an unregistered domain here is either a caller error (typo,
    stale domain string) or a genuinely new domain that hasn't been
    registered in pipeline/dispatch.py yet - either way, fail the job loudly
    rather than silently classifying it against the wrong domain's prompt
    and schema.
    """
    update_job_status(job_id, "running")
    try:
        articles = await get_run_articles(news_run_id)
    except NewsRetrievalError:
        logger.exception("Pre-classification pipeline failed for job %d", job_id)
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    usable = [a for a in articles if has_usable_body(a)]
    if limit is not None:
        usable = usable[:limit]
    update_job_status(job_id, "running", article_count=len(usable))

    domain_config = get_domain_config(domain)
    if domain_config is None:
        logger.error(
            "No classifier registered for domain=%r (job %d) - known domains: %s",
            domain, job_id, ", ".join(known_domains()),
        )
        update_job_status(job_id, "failed", set_completed_at=True)
        return

    batch_context = [
        {"title": a.get("title", ""), "url": a.get("url", "")}
        for a in usable[:20]
    ]

    semaphore = asyncio.Semaphore(config.CLASSIFY_CONCURRENCY)
    loop = asyncio.get_event_loop()

    async def classify_one(article: dict[str, Any]) -> bool:
        """Classify a single article; returns True if skipped."""
        async with semaphore:
            try:
                result = await loop.run_in_executor(
                    _executor,
                    lambda a=article: domain_config.classify_one(a, batch_context=batch_context),
                )
                domain_config.insert_fn(job_id, article, result)
                return False
            except Exception:
                logger.exception(
                    "Classification failed for article %s (job %d, domain=%s)",
                    article.get("url"), job_id, domain,
                )
                return True

    outcomes = await asyncio.gather(*[classify_one(a) for a in usable])
    skipped = sum(outcomes)

    if skipped == len(usable) and usable:
        update_job_status(job_id, "failed", set_completed_at=True)
    else:
        update_job_status(job_id, "completed", set_completed_at=True)
