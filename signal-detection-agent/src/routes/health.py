"""GET /health - liveness check."""
from fastapi import APIRouter

from db import get_db

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    try:
        with get_db() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
