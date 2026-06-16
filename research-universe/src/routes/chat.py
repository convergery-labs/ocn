"""POST /chat - streaming SSE agent endpoint."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import agent.agent as agent
from auth import get_current_user

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None

    model_config = {"str_max_length": 4000}


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat")
def chat(
    body: ChatRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream one user turn through the agent as Server-Sent Events.

    Events:
      thinking  {"tool": str, "label": str}   — emitted for each tool call
      done      {message, card_type, card_data, conversation_id}
      error     {"message": str}
    """
    def generate():
        for evt in agent.run_streaming(
            message=body.message,
            conversation_id=body.conversation_id,
            user_id=current_user["id"],
            user_name=current_user["name"],
        ):
            yield _sse(evt["event"], evt["data"])

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
