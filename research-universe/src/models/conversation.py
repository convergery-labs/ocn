"""DB query functions for universe_conversations."""
from __future__ import annotations

import json
from typing import Any

from db import get_db


def get_or_create(
    conversation_id: str | None,
    user_id: str,
) -> tuple[str, list[dict]]:
    """Return (conversation_id, messages_list).

    If conversation_id is provided and exists, load it.
    Otherwise create a new conversation and return its id.
    """
    with get_db() as conn:
        if conversation_id:
            cur = conn.execute(
                "SELECT id::text, messages FROM universe_conversations WHERE id = :id",
                {"id": conversation_id},
            )
            row = cur.fetchone()
            if row:
                msgs = row["messages"]
                return row["id"], (msgs if isinstance(msgs, list) else json.loads(msgs))

        # Create new
        cur = conn.execute(
            """
            INSERT INTO universe_conversations (user_id, messages)
            VALUES (:user_id, '[]'::jsonb)
            RETURNING id::text
            """,
            {"user_id": user_id},
        )
        new_id = cur.fetchone()["id"]
        return new_id, []


_MAX_MESSAGES = 200  # ~100 user turns; keeps JSONB blob manageable


def save(conversation_id: str, messages: list[dict]) -> None:
    """Persist the updated message list, trimming to the most recent messages."""
    # Always keep the most recent messages - drop oldest when over cap
    trimmed = messages[-_MAX_MESSAGES:] if len(messages) > _MAX_MESSAGES else messages
    with get_db() as conn:
        conn.execute(
            """
            UPDATE universe_conversations
               SET messages   = :messages::jsonb,
                   updated_at = NOW()
             WHERE id = :id
            """,
            {"id": conversation_id, "messages": json.dumps(trimmed, default=str)},
        )
