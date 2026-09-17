"""GET /jobs - job listing and results endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_auth
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
    caller: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Return paginated classification results across all jobs, newest first."""
    return list_all_results(limit=limit, cursor=cursor, signal_detection=signal_detection, source_type=source_type, ticker=ticker, period=period, source_category=source_category, grade=grade, impacted_category=impacted_category, impacted_ticker=impacted_ticker, channel=channel, corroborated=corroborated, published_from=published_from, published_to=published_to)


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
    caller: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return list_results(job_id=job_id, limit=limit, cursor=cursor, signal_detection=signal_detection, source_type=source_type, ticker=ticker, period=period, source_category=source_category, grade=grade, impacted_category=impacted_category, impacted_ticker=impacted_ticker, channel=channel, corroborated=corroborated, published_from=published_from, published_to=published_to)
