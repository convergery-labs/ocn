"""Route for GET /health."""
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health() -> JSONResponse:
    """Return health status of the service and its configuration."""
    checks: dict[str, bool] = {
        "news_retrieval_url_configured": bool(
            os.environ.get("NEWS_RETRIEVAL_URL")
        ),
        "news_retrieval_api_key_configured": bool(
            os.environ.get("NEWS_RETRIEVAL_API_KEY")
        ),
    }
    healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": checks,
        },
    )
