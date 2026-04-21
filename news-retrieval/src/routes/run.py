"""Route for POST /run."""
import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response

from auth import require_auth
from controllers.run import (
    RunConflictError,
    RunRequest,
    create_run_record,
    run_pipeline,
)
from models.api_keys import ApiKeyRow

router = APIRouter()


@router.post("/run", status_code=202)
async def run(
    request: RunRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    caller: ApiKeyRow = Depends(require_auth),
) -> dict:
    """Accept a pipeline run request and start it in the background."""
    try:
        result = await asyncio.to_thread(
            create_run_record, request, caller
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except RunConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Run already in progress",
                "run_id": exc.run_id,
            },
        )
    if result["cache_hit"]:
        response.status_code = 200
        return {**result["cached_run"], "cache_hit": True}
    background_tasks.add_task(
        run_pipeline, result["run_id"], request
    )
    return {"run_id": result["run_id"], "status": "running"}
