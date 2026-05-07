"""Webhook callback routes from news-retrieval and signal-detection."""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhook/news-retrieval")
async def news_retrieval_webhook(body: dict) -> JSONResponse:
    """Receive completion callback from news-retrieval.

    The payload contains run_id and status. In the current A2A flow
    the background task uses polling, so this endpoint exists for
    future callback-driven orchestration and logs the event.
    """
    logger.info(
        "news-retrieval callback received: run_id=%s status=%s",
        body.get("run_id"),
        body.get("status"),
    )
    return JSONResponse(content={"acknowledged": True})


@router.post("/webhook/signal-detection")
async def signal_detection_webhook(body: dict) -> JSONResponse:
    """Receive completion callback from signal-detection.

    The payload contains job_id and status. Logs the event for
    observability; polling-based background tasks do not depend on it.
    """
    logger.info(
        "signal-detection callback received: job_id=%s status=%s",
        body.get("job_id"),
        body.get("status"),
    )
    return JSONResponse(content={"acknowledged": True})
