"""Route for POST /run — unified fetch-and-classify pipeline."""
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import require_auth
from controllers.classify import submit_classify_job
from controllers.run import fetch_and_classify

router = APIRouter()


class PipelineRunRequest(BaseModel):
    """Request body for POST /run."""

    domain: str
    days_back: int = Field(default=7, ge=1)
    max_articles: int | None = Field(default=None, ge=1)
    focus: str | None = Field(default=None)
    callback_url: str | None = Field(default=None)
    force: bool = Field(default=False)


@router.post("/run", status_code=202)
async def post_run(
    body: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    caller: dict[str, Any] = Depends(require_auth),
) -> JSONResponse:
    """Trigger a full fetch-and-classify pipeline run (202 Accepted)."""
    job = await submit_classify_job(
        run_id=None,
        articles=[],
        callback_url=body.callback_url,
        domain=body.domain,
    )
    background_tasks.add_task(
        fetch_and_classify, job["id"], body, body.callback_url
    )
    return JSONResponse(
        status_code=202,
        content={"job_id": job["id"], "status": job["status"]},
    )
