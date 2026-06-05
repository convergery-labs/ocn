"""GET /health - liveness + DB connectivity check."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db import get_db

router = APIRouter()


@router.get("/health")
def health() -> JSONResponse:
    """ALB health check. Returns 503 if the DB is unreachable."""
    try:
        with get_db() as conn:
            conn.execute("SELECT 1")
        return JSONResponse({"status": "ok", "service": "research-universe"})
    except Exception:
        return JSONResponse(
            {"status": "degraded", "detail": "Database unavailable"},
            status_code=503,
        )
