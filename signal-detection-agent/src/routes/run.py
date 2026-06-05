"""POST /run - trigger the agent classification pipeline."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import require_auth
from controllers.run import run_agent_pipeline, submit_run

router = APIRouter()


class RunRequest(BaseModel):
    domain: str
    run_id: int | None = None
    limit: int | None = None
    days_back: int = 7
    use_latest_run: bool = False
    force: bool = False


@router.post("/run")
async def trigger_run(
    body: RunRequest,
    background_tasks: BackgroundTasks,
    caller: dict[str, Any] = Depends(require_auth),
) -> JSONResponse:
    job_id, news_run_id, cached = await submit_run(
        domain=body.domain,
        run_id=body.run_id,
        days_back=body.days_back,
        use_latest_run=body.use_latest_run,
        force=body.force,
    )
    if cached:
        return JSONResponse(status_code=200, content={"job_id": job_id, "cached": True})
    background_tasks.add_task(run_agent_pipeline, job_id, body.domain, news_run_id, body.limit)
    return JSONResponse(status_code=202, content={"job_id": job_id, "cached": False})
