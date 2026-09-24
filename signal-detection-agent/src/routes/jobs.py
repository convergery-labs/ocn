"""GET /jobs - job listing and results endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_auth
from controllers.run import generate_korea_signal_summary_for_date
from models.jobs import get_job, list_all_results, list_jobs, list_results, list_taiwan_periods

router = APIRouter()


@router.get("/results")
async def get_all_results(
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
    signal_detection: str | None = Query(default=None),
    source_type: str | None = Query(default=None, description="Filter by source_type, e.g. 'news' or 'sec_filing'"),
    ticker: str | None = Query(default=None, description="Filter by ticker (only populated for source_type='sec_filing' today)"),
    period: str | None = Query(default=None, description="Filter by metadata.period_gregorian, e.g. '2026-07' (only populated for taiwan_market_signal mops_revenue rows)"),
    source_category: str | None = Query(default=None, description="Filter by metadata.source_category, e.g. 'mops_revenue', 'mops_material', 'gdelt' (only populated for taiwan_market_signal rows)"),
    grade: str | None = Query(default=None, description="Filter by metadata.grade: 'TOP', 'STRONG', or 'STANDARD' (only populated for geopolitical_signal rows Stage D has graded)"),
    impacted_category: str | None = Query(default=None, description="Filter to rows whose metadata.impacted_categories includes this exact category name, e.g. 'Semiconductor Manufacturing' (only populated for geopolitical_signal rows Stage C has tagged)"),
    impacted_ticker: str | None = Query(default=None, description="Filter to rows whose metadata.impacted_companies_direct OR metadata.impacted_companies_by_category includes this ticker, e.g. 'NVDA' (only populated for geopolitical_signal rows Stage C has tagged; case-insensitive)"),
    channel: str | None = Query(default=None, description="Filter by metadata.channel: 'energy', 'trade', 'sanctions', 'shipping', or 'conflict' (only populated for geopolitical_signal rows Stage C has tagged)"),
    corroborated: bool | None = Query(default=None, description="Filter by metadata.corroborated (only populated for geopolitical_signal rows Stage D has graded)"),
    published_from: str | None = Query(default=None, description="Filter to rows with published >= this date (YYYY-MM-DD), inclusive"),
    published_to: str | None = Query(default=None, description="Filter to rows with published <= this date (YYYY-MM-DD), inclusive"),
    macro_series: str | None = Query(default=None, description="Filter to macro_signal rows involving this series_id, e.g. 'DGS10' - matches either an interpreted event's member_series or a suppressed/audit row's own series_id"),
    macro_suspect: bool | None = Query(default=None, description="Filter by metadata.suspect (only populated for source_type='macro_signal' interpreted-event rows - the model's calendar-mechanics override flag from Appendix A)"),
    macro_interpreted_only: bool | None = Query(default=None, description="true: only macro_signal rows that reached and passed INTERPRET (a real LLM call, real channel/entry_point/assets/transmission fields) - excludes suppressed/NOISE audit rows kept only for the 'nothing is ever deleted' audit trail, which otherwise mix in with real signal_detection='signal'/'weak_signal' results. false: only the suppressed/audit rows. Use plain signal_detection ('signal'/'weak_signal'/'noise') for macro_signal's HIGH/WEAK/NOISE tier - same convention as every other domain, no separate macro-specific tier filter."),
    caller: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Return paginated classification results across all jobs, newest first."""
    return list_all_results(limit=limit, cursor=cursor, signal_detection=signal_detection, source_type=source_type, ticker=ticker, period=period, source_category=source_category, grade=grade, impacted_category=impacted_category, impacted_ticker=impacted_ticker, channel=channel, corroborated=corroborated, published_from=published_from, published_to=published_to, macro_series=macro_series, macro_suspect=macro_suspect, macro_interpreted_only=macro_interpreted_only)


@router.get("/korea-signals/summary")
async def get_korea_signal_summary(
    date: str | None = Query(default=None, description="YYYY-MM-DD (UTC). Defaults to today (UTC)."),
    caller: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Spec Section 8.4's twice-daily trader summary, generated on demand
    for one day's already-classified korea_market_signal rows (reads
    agent_classifications directly - no news-retrieval fetch, no
    re-classification; see generate_korea_signal_summary_for_date's own
    docstring).

    Not paginated/streamed - this returns one finished text block per
    call, same shape the CLI's summarize-korea-signals command logs.
    Calling this twice for the same date before new rows are inserted is
    expected to return the same or near-identical text - the row
    selection/ordering is fully deterministic (see
    generate_korea_signal_summary_for_date), and the model call itself
    uses temperature=0 (see korea_signal_summary.py's own payload), same
    as every other LLM call in this module - not a hard guarantee of
    byte-identical output across calls, but not free-running temperature
    either.
    """
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summary = generate_korea_signal_summary_for_date(date)
    return {"date": date, "summary": summary}


@router.get("/results/periods")
async def get_taiwan_periods(
    source_category: str | None = Query(default=None, description="Scope to one source_category, e.g. 'mops_revenue' or 'mops_material'. Omit for periods across both."),
    caller: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Return every distinct period (metadata.period_gregorian) that exists
    for taiwan_market_signal, newest first - backs a period filter/picker
    without a client-side scan over a fetched page. Always scoped to
    source_type='taiwan_market_signal'; that's the only source_type with
    period_gregorian populated today.
    """
    return {"periods": list_taiwan_periods(source_category=source_category)}


@router.get("/jobs")
async def get_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default="completed"),
    domain: str | None = Query(default=None, description="Filter by agent_jobs.domain, e.g. 'ai_news' or 'sec_filing'"),
    caller: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    return list_jobs(limit=limit, cursor=cursor, status=status, domain=domain)


@router.get("/jobs/{job_id}")
async def get_job_by_id(
    job_id: int,
    caller: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}/results")
async def get_job_results(
    job_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
    signal_detection: str | None = Query(default=None),
    source_type: str | None = Query(default=None, description="Filter by source_type, e.g. 'news' or 'sec_filing'"),
    ticker: str | None = Query(default=None, description="Filter by ticker (only populated for source_type='sec_filing' today)"),
    period: str | None = Query(default=None, description="Filter by metadata.period_gregorian, e.g. '2026-07' (only populated for taiwan_market_signal mops_revenue rows)"),
    source_category: str | None = Query(default=None, description="Filter by metadata.source_category, e.g. 'mops_revenue', 'mops_material', 'gdelt' (only populated for taiwan_market_signal rows)"),
    grade: str | None = Query(default=None, description="Filter by metadata.grade: 'TOP', 'STRONG', or 'STANDARD' (only populated for geopolitical_signal rows Stage D has graded)"),
    impacted_category: str | None = Query(default=None, description="Filter to rows whose metadata.impacted_categories includes this exact category name, e.g. 'Semiconductor Manufacturing' (only populated for geopolitical_signal rows Stage C has tagged)"),
    impacted_ticker: str | None = Query(default=None, description="Filter to rows whose metadata.impacted_companies_direct OR metadata.impacted_companies_by_category includes this ticker, e.g. 'NVDA' (only populated for geopolitical_signal rows Stage C has tagged; case-insensitive)"),
    channel: str | None = Query(default=None, description="Filter by metadata.channel: 'energy', 'trade', 'sanctions', 'shipping', or 'conflict' (only populated for geopolitical_signal rows Stage C has tagged)"),
    corroborated: bool | None = Query(default=None, description="Filter by metadata.corroborated (only populated for geopolitical_signal rows Stage D has graded)"),
    published_from: str | None = Query(default=None, description="Filter to rows with published >= this date (YYYY-MM-DD), inclusive"),
    published_to: str | None = Query(default=None, description="Filter to rows with published <= this date (YYYY-MM-DD), inclusive"),
    macro_series: str | None = Query(default=None, description="Filter to macro_signal rows involving this series_id, e.g. 'DGS10' - matches either an interpreted event's member_series or a suppressed/audit row's own series_id"),
    macro_suspect: bool | None = Query(default=None, description="Filter by metadata.suspect (only populated for source_type='macro_signal' interpreted-event rows - the model's calendar-mechanics override flag from Appendix A)"),
    macro_interpreted_only: bool | None = Query(default=None, description="true: only macro_signal rows that reached and passed INTERPRET (a real LLM call, real channel/entry_point/assets/transmission fields) - excludes suppressed/NOISE audit rows kept only for the 'nothing is ever deleted' audit trail, which otherwise mix in with real signal_detection='signal'/'weak_signal' results. false: only the suppressed/audit rows. Use plain signal_detection ('signal'/'weak_signal'/'noise') for macro_signal's HIGH/WEAK/NOISE tier - same convention as every other domain, no separate macro-specific tier filter."),
    caller: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return list_results(job_id=job_id, limit=limit, cursor=cursor, signal_detection=signal_detection, source_type=source_type, ticker=ticker, period=period, source_category=source_category, grade=grade, impacted_category=impacted_category, impacted_ticker=impacted_ticker, channel=channel, corroborated=corroborated, published_from=published_from, published_to=published_to, macro_series=macro_series, macro_suspect=macro_suspect, macro_interpreted_only=macro_interpreted_only)
