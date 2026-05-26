"""GET /health route."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness check."""
    return {"status": "ok"}
