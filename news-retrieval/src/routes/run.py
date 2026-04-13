"""Route for POST /run."""
import asyncio

from fastapi import APIRouter, HTTPException

from controllers.run import RunRequest, execute

router = APIRouter()


@router.post("/run")
async def run(request: RunRequest) -> dict:
    """Run the two-pass aggregation pipeline for the given domain."""
    try:
        return await asyncio.to_thread(execute, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
