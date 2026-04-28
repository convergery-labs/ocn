"""Route for GET /health."""
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_REQUIRED_VARS = [
    "GATEWAY_AUTH_URL",
    "GATEWAY_NEWS_URL",
    "GATEWAY_SIGNAL_URL",
]


@router.get("/health")
async def health() -> JSONResponse:
    """Return 200 if all upstream URLs are configured, 503 otherwise."""
    checks = {
        var: bool(os.environ.get(var))
        for var in _REQUIRED_VARS
    }
    if all(checks.values()):
        return JSONResponse(status_code=200, content={"status": "ok"})
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "checks": checks},
    )
