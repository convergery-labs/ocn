"""Route for GET /health."""
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health() -> JSONResponse:
    """Return health status of the server and its dependencies."""
    checks: dict[str, bool] = {}
    checks["api_key_configured"] = bool(
        os.environ.get("OPENROUTER_API_KEY")
    )
    checks["model_configured"] = bool(os.environ.get("OPENROUTER_MODEL"))

    healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": checks,
        },
    )
