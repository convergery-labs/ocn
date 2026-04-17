"""Routes for /runs."""
from fastapi import APIRouter, HTTPException

from models.articles import list_articles_for_run
from models.runs import get_run, list_runs

router = APIRouter()


@router.get("/runs")
def get_runs() -> list:
    """Return all pipeline runs, newest first."""
    return list_runs()


@router.get("/runs/{run_id}")
def get_run_by_id(run_id: int) -> dict:
    """Return a single pipeline run by id."""
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.get("/runs/{run_id}/articles")
def get_articles_for_run(run_id: int) -> list:
    """Return all articles for a run."""
    if get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return list_articles_for_run(run_id)
