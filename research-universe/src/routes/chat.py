"""POST /chat - agent endpoint."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import agent.agent as agent
from auth import get_current_user

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None

    model_config = {"str_max_length": 4000}  # ~1 page of text - enough for any real query


class ChatResponse(BaseModel):
    message: str
    card_type: str | None = None
    card_data: dict | None = None
    conversation_id: str


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict:
    """Run one user turn through the agent and return a structured response."""
    return agent.run(
        message=body.message,
        conversation_id=body.conversation_id,
        user_id=current_user["id"],
        user_name=current_user["name"],
    )
