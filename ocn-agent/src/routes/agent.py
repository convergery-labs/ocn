"""Routes for /agent endpoints."""
import asyncio
import logging

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import pending
from graph import graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent")


class QueryRequest(BaseModel):
    """Request body for POST /agent/query."""

    prompt: str
    callback_url: str


async def _fire_failure(callback_url: str, message: str) -> None:
    """POST a failure payload; best-effort, 10-second timeout."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                callback_url,
                json={"status": "failed", "message": message},
            )
    except Exception as exc:
        logger.warning(
            "Failure callback delivery failed to %s: %s", callback_url, exc
        )


async def _run_graph(prompt: str, callback_url: str) -> None:
    """Invoke the agent graph and deliver any unhandled exception as failure."""
    try:
        await graph.ainvoke({"prompt": prompt, "callback_url": callback_url})
    except Exception as exc:
        logger.exception("Agent graph failed: %s", exc)
        await _fire_failure(callback_url, str(exc))


@router.post("/query", status_code=202)
async def query(request: QueryRequest) -> JSONResponse:
    """Accept a natural-language query and start async processing."""
    asyncio.create_task(
        _run_graph(request.prompt, request.callback_url)
    )
    return JSONResponse(status_code=202, content={"status": "accepted"})


@router.post("/news-retrieval-callback/{correlation_id}")
async def news_retrieval_callback(
    correlation_id: str, payload: dict
) -> dict:
    """Receive a completion webhook from news-retrieval."""
    event = pending.run_events.get(correlation_id)
    if event is None:
        logger.warning(
            "Received stale news-retrieval callback: %s", correlation_id
        )
        return {"ok": True}
    pending.run_results[correlation_id] = payload
    event.set()
    return {"ok": True}


@router.post("/categorise")
async def categorise() -> JSONResponse:
    """Categorise stub — not yet implemented."""
    return JSONResponse(
        status_code=501, content={"detail": "Not implemented"}
    )
