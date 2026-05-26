"""A2A-compatible routes: Agent Card and JSON-RPC tasks/send."""
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from controllers.digest import run_digest_async

router = APIRouter()

_AGENT_CARD: dict[str, Any] = {
    "schema_version": "0.1",
    "name": "signal-herald",
    "description": (
        "Daily AI signal intelligence digest agent. Triggers the "
        "signal-detection-agent pipeline, groups all classified articles "
        "(signal, weak_signal, noise) into 11 AI-universe categories, "
        "generates LLM summaries, and emails a digest."
    ),
    "url": "http://signal-herald",
    "version": "1.0.0",
    "capabilities": {
        "tasks": True,
        "streaming": False,
    },
    "skills": [
        {
            "id": "run_digest",
            "name": "Run digest",
            "description": (
                "Check for today's signal-detection-agent job, trigger "
                "the pipeline if needed, and send the daily digest email."
            ),
            "input_modes": ["text"],
            "output_modes": ["text"],
        }
    ],
}


@router.get("/.well-known/agent.json")
def agent_card() -> dict:
    """Return the A2A Agent Card."""
    return _AGENT_CARD


@router.post("/")
async def jsonrpc(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """JSON-RPC 2.0 dispatcher. Handles tasks/send."""
    try:
        body = await request.json()
    except Exception:
        return _error_response(None, -32700, "Parse error")

    rpc_id = body.get("id")
    method = body.get("method")

    if body.get("jsonrpc") != "2.0":
        return _error_response(rpc_id, -32600, "Invalid Request")

    if method == "tasks/send":
        task_id = str(uuid.uuid4())
        background_tasks.add_task(run_digest_async)
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "id": task_id,
                    "status": {"state": "submitted"},
                },
            }
        )

    return _error_response(rpc_id, -32601, "Method not found")


def _error_response(rpc_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        content={
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": code, "message": message},
        }
    )
