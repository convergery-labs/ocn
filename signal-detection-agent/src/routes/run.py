"""POST /run — trigger the agent classification pipeline."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from auth import require_auth
from controllers.run import run_agent_pipeline, submit_run

router = APIRouter()


class RunRequest(BaseModel):
    domain: str
    run_id: int | None = None
    limit: int | None = None


@router.post("/run", status_code=202)
async def trigger_run(
    body: RunRequest,
    background_tasks: BackgroundTasks,
    caller: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    job_id = await submit_run(domain=body.domain, run_id=body.run_id)
    background_tasks.add_task(run_agent_pipeline, job_id, body.domain, body.run_id, body.limit)
    return {"job_id": job_id}
