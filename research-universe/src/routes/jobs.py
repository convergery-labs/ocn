"""Discovery job routes - POST /jobs/scan + GET /jobs/{job_id}."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

import models.scan_job as scan_job_model
import models.taxonomy as taxonomy_model
from agent.discovery import run_scan
from auth import get_current_user

router = APIRouter(prefix="/jobs", tags=["jobs"])


# --------------------------------------------------------------------------- #
# Pydantic schemas                                                             #
# --------------------------------------------------------------------------- #

class ScanRequest(BaseModel):
    categories: list[int] | None = None  # None → scan all 19


class CategoryResult(BaseModel):
    category_id: int
    category_name: str
    status: str
    proposed: int
    skipped: int


class ScanJobResponse(BaseModel):
    job_id: str
    status: str
    categories_total: int
    categories_done: int
    companies_proposed: int
    companies_skipped: int
    category_results: list[CategoryResult]
    started_at: Any
    completed_at: Any | None


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #

@router.post("/scan", response_model=dict, status_code=202)
def start_scan(
    body: ScanRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Start a universe discovery scan in the background.

    Loops through all (or specified) categories, asks Claude to find missing
    companies, deduplicates against the existing universe, and adds new ones
    as pending_review.
    """
    # Prevent concurrent scans - only one running job allowed at a time
    if scan_job_model.has_running_job():
        raise HTTPException(
            status_code=409,
            detail="A scan is already running. Wait for it to complete before starting another.",
        )

    # Resolve which categories to scan
    if body.categories:
        category_ids = body.categories
    else:
        cats = taxonomy_model.list_categories()
        category_ids = [c["id"] for c in cats]

    triggered_by = current_user["name"]
    job_id = scan_job_model.create(category_ids, triggered_by)

    background_tasks.add_task(run_scan, job_id, category_ids, triggered_by)

    return {
        "job_id": job_id,
        "status": "running",
        "categories_total": len(category_ids),
        "message": f"Scan started for {len(category_ids)} categories. Poll GET /jobs/{job_id} for progress.",
    }


@router.get("/scan/{job_id}", response_model=ScanJobResponse)
def get_scan_job(job_id: str) -> dict[str, Any]:
    """Return current status and progress of a scan job."""
    job = scan_job_model.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job



@router.get("/schedule", response_model=dict)
def get_schedule(
    _: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return last_run_at and next_run_at for the 15-day sweep."""
    from datetime import datetime, timedelta, timezone

    last_run_at = scan_job_model.get_last_run_at()

    now = datetime.now(timezone.utc)
    if last_run_at:
        last_dt = last_run_at if isinstance(last_run_at, datetime) else datetime.fromisoformat(str(last_run_at))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        next_run_at = last_dt + timedelta(days=15)
    else:
        next_run_at = now + timedelta(days=15)

    return {
        "last_run_at": last_run_at,
        "next_run_at": next_run_at.isoformat(),
    }
