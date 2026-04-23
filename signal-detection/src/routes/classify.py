"""Routes for POST /classify and GET /classifications/* endpoints."""
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import require_auth
from controllers.classify import (
    DuplicateJobError,
    RunNotFoundError,
    run_classification_stub,
    submit_classify_job,
)
from models.jobs import _decode_cursor, get_job, get_job_stats, list_job_results

router = APIRouter()


class ArticleIn(BaseModel):
    """A directly submitted article."""

    url: str
    title: str
    body: str
    source: str | None = None
    published: str | None = None


class ClassifyRequest(BaseModel):
    """Request body for POST /classify.

    Exactly one of run_id or articles must be provided.
    """

    run_id: int | None = Field(default=None)
    article_ids: list[int] | None = Field(default=None)
    articles: list[ArticleIn] | None = Field(default=None)
    callback_url: str | None = Field(default=None)

    def mode_a_articles(self) -> list[dict]:
        """Return stub article dicts for Mode A (article_ids or empty)."""
        if self.article_ids:
            return [{"id": aid} for aid in self.article_ids]
        return []

    def mode_b_articles(self) -> list[dict]:
        """Return article dicts for Mode B (direct submission)."""
        return [a.model_dump() for a in (self.articles or [])]


@router.post("/classify", status_code=202)
async def post_classify(
    body: ClassifyRequest,
    background_tasks: BackgroundTasks,
    caller: dict[str, Any] = Depends(require_auth),
) -> JSONResponse:
    """Create a classification job and enqueue background processing."""
    has_run_id = body.run_id is not None
    has_articles = bool(body.articles)
    if not has_run_id and not has_articles:
        raise HTTPException(
            status_code=422,
            detail="Provide either run_id or articles.",
        )
    if has_run_id and has_articles:
        raise HTTPException(
            status_code=422,
            detail="Provide run_id or articles, not both.",
        )

    articles = (
        body.mode_a_articles() if has_run_id else body.mode_b_articles()
    )
    run_id_str = str(body.run_id) if has_run_id else None

    try:
        job = await submit_classify_job(
            run_id=run_id_str,
            articles=articles,
            callback_url=body.callback_url,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DuplicateJobError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    background_tasks.add_task(
        run_classification_stub,
        job["id"],
        articles,
        body.callback_url,
    )
    return JSONResponse(
        status_code=202,
        content={"job_id": job["id"], "status": job["status"]},
    )


@router.get("/classifications/{job_id}")
def get_classification(
    job_id: int,
    caller: dict[str, Any] = Depends(require_auth),
) -> dict:
    """Return job status and aggregate stats."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=f"Job {job_id} not found."
        )
    stats = (
        get_job_stats(job_id)
        if job["status"] == "completed"
        else None
    )
    return {
        "job_id": job["id"],
        "run_id": job["run_id"],
        "status": job["status"],
        "created_at": (
            job["created_at"].isoformat()
            if job["created_at"] else None
        ),
        "completed_at": (
            job["completed_at"].isoformat()
            if job["completed_at"] else None
        ),
        "article_count": job["article_count"],
        "stats": stats,
    }


@router.get("/classifications/{job_id}/results")
def get_classification_results(
    job_id: int,
    limit: int = 20,
    cursor: str | None = None,
    caller: dict[str, Any] = Depends(require_auth),
) -> dict:
    """Return paginated classification results for a job."""
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=422, detail="limit must be between 1 and 100."
        )
    job = get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=f"Job {job_id} not found."
        )
    after_id = 0
    if cursor:
        try:
            after_id = _decode_cursor(cursor)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid cursor."
            )
    results, next_cursor = list_job_results(
        job_id=job_id, after_id=after_id, limit=limit
    )
    return {
        "results": [
            {
                **r,
                "created_at": (
                    r["created_at"].isoformat()
                    if r.get("created_at") else None
                ),
            }
            for r in results
        ],
        "next_cursor": next_cursor,
    }
