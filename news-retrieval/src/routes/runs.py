"""Routes for /runs."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from models.articles import list_articles_for_run
from models.runs import get_run, list_runs

router = APIRouter()


@router.get("/runs")
def get_runs(
    domain: list[str] = Query(default=[]),
    status: Optional[Literal["running", "completed", "failed"]] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = None,
) -> dict:
    """Return filtered, paginated pipeline runs, newest first."""
    try:
        runs, next_cursor = list_runs(
            domains=domain or None,
            status=status,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            cursor=cursor,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid cursor.")
    return {"runs": runs, "next_cursor": next_cursor}


@router.get("/runs/{run_id}")
def get_run_by_id(run_id: int) -> dict:
    """Return a single pipeline run by id."""
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.get("/runs/{run_id}/articles")
def get_articles_for_run(
    run_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = None,
    include_body: bool = False,
) -> dict:
    """Return paginated articles for a run."""
    if get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    try:
        articles, next_cursor = list_articles_for_run(
            run_id, limit=limit, cursor=cursor, include_body=include_body
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid cursor.")
    return {"articles": articles, "next_cursor": next_cursor}
