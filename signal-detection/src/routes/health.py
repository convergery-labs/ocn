"""Route for GET /health."""
import asyncio
import os

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db import get_db

router = APIRouter()


async def _check_qdrant() -> bool:
    """Return True if the Qdrant health endpoint responds with HTTP 200."""
    qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
    qdrant_port = os.environ.get("QDRANT_PORT", "6333")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"http://{qdrant_host}:{qdrant_port}/healthz"
            )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


async def _check_auth_service() -> bool | None:
    """Return True/False if AUTH_SERVICE_URL is set, else None."""
    auth_service_url = os.environ.get("AUTH_SERVICE_URL")
    if not auth_service_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{auth_service_url}/health")
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


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

    qdrant_result, auth_result = await asyncio.gather(
        _check_qdrant(),
        _check_auth_service(),
    )

    checks["qdrant"] = qdrant_result
    if auth_result is not None:
        checks["auth_service"] = auth_result

    healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": checks,
        },
    )
