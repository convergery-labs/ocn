"""Webhook callback stubs from signal-detection-agent."""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhook/signal-detection-agent")
async def signal_agent_webhook(body: dict) -> JSONResponse:
    """Receive completion callback from signal-detection-agent."""
    logger.info(
        "signal-detection-agent callback received: job_id=%s status=%s",
        body.get("job_id"),
        body.get("status"),
    )
    return JSONResponse(content={"acknowledged": True})
