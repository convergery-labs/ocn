"""Route for POST /run."""
import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from auth import require_auth
from controllers.run import RunRequest, create_run_record, run_pipeline
from models.api_keys import ApiKeyRow

router = APIRouter()


@router.post("/run", status_code=202)
async def run(
    request: RunRequest,
    background_tasks: BackgroundTasks,
    caller: ApiKeyRow = Depends(require_auth),
) -> dict:
    """Accept a pipeline run request and start it in the background."""
    try:
        run_id = await asyncio.to_thread(
            create_run_record, request, caller
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    background_tasks.add_task(run_pipeline, run_id, request)
    return {"run_id": run_id, "status": "running"}
