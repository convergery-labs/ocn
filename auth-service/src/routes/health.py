"""Route for GET /health."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health() -> JSONResponse:
    """Return liveness status of the auth-service."""
    return JSONResponse(status_code=200, content={"status": "ok"})
