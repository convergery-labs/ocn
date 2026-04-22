"""Route for GET /health."""
import os

import httpx
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

    auth_service_url = os.environ.get("AUTH_SERVICE_URL")
    if auth_service_url:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{auth_service_url}/health")
            checks["auth_service"] = resp.status_code == 200
        except httpx.HTTPError:
            checks["auth_service"] = False

    healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": checks,
        },
    )
