"""Route for POST /run."""
import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException

from controllers.run import RunRequest, create_run_record, run_pipeline

router = APIRouter()


@router.post("/run", status_code=202)
async def run(
    request: RunRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Accept a pipeline run request and start it in the background."""
    try:
        run_id = await asyncio.to_thread(create_run_record, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    background_tasks.add_task(run_pipeline, run_id, request)
    return {"run_id": run_id, "status": "running"}
