"""Routes for /runs."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from models.articles import (
    list_articles_for_category,
    list_articles_for_run,
)
from models.categories import list_categories
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


@router.get("/runs/{run_id}/categories")
def get_categories_for_run(run_id: int) -> list:
    """Return all categories for a run."""
    if get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return list_categories(run_id)


@router.get("/runs/{run_id}/articles")
def get_articles_for_run(
    run_id: int,
    category_id: Optional[int] = Query(
        default=None,
        description="Filter articles to a specific category.",
    ),
) -> list:
    """Return articles for a run, optionally filtered by category."""
    if get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if category_id is not None:
        cats = list_categories(run_id)
        if not any(c["id"] == category_id for c in cats):
            raise HTTPException(
                status_code=404,
                detail="Category not found for this run.",
            )
        return list_articles_for_category(run_id, category_id)
    return list_articles_for_run(run_id)
