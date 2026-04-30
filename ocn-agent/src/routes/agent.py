"""Stub routes for /agent endpoints."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/agent")


@router.post("/query")
async def query() -> JSONResponse:
    """Query stub — not yet implemented."""
    return JSONResponse(
        status_code=501, content={"detail": "Not implemented"}
    )


@router.post("/categorise")
async def categorise() -> JSONResponse:
    """Categorise stub — not yet implemented."""
    return JSONResponse(
        status_code=501, content={"detail": "Not implemented"}
    )
