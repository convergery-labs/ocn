"""Route for GET /health."""
import os

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db import get_db

router = APIRouter()


@router.get("/health")
async def health() -> JSONResponse:
    """Return health status of the server and its dependencies."""
    checks: dict[str, bool] = {}

    try:
        with get_db() as conn:
            conn.execute("SELECT 1")
        checks["postgres"] = True
    except Exception:
        checks["postgres"] = False

    qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
    qdrant_port = os.environ.get("QDRANT_PORT", "6333")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"http://{qdrant_host}:{qdrant_port}/healthz"
            )
        checks["qdrant"] = resp.status_code == 200
    except httpx.HTTPError:
        checks["qdrant"] = False

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
