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
    reports_dir = os.environ.get("REPORTS_DIR", "/app/reports")
    try:
        os.makedirs(reports_dir, exist_ok=True)
        test_path = os.path.join(reports_dir, ".healthcheck")
        with open(test_path, "w") as f:
            f.write("")
        os.remove(test_path)
        checks["reports_dir_writable"] = True
    except OSError:
        checks["reports_dir_writable"] = False

    healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": checks,
        },
    )
