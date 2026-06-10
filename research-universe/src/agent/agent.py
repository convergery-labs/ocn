"""Claude agent orchestration - tool-use loop for research-universe."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI

import models.conversation as conv_model
from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOL_DEFINITIONS, execute_tool

log = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10

# Tools whose results determine the UI card shown to the user
_CARD_TOOLS = {
    "search_companies", "get_company", "create_company",
    "update_company", "verify_company", "list_pending",  # "find_peers" disabled
}
_MATCH_THRESHOLD = 0.7  # minimum search score to show a company_card


def _card_from_tool(tool_name: str, result_str: str) -> tuple[str | None, dict | None]:
    """Derive card_type and card_data directly from a tool result.

    This avoids asking Claude to reformat data it already received,
    saving the tokens that formatting would cost.
    """
    try:
        result = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return None, None

    if isinstance(result, dict) and "error" in result:
        return None, None

    if tool_name == "search_companies":
        companies = result.get("companies", [])
        if companies and companies[0].get("match_score", 0) >= _MATCH_THRESHOLD:
            return "company_card", companies[0]
        return None, None

    if tool_name in ("get_company", "verify_company"):
        return "company_card", result

    if tool_name in ("create_company", "update_company"):
        return "proposed_entry", result

    # if tool_name == "find_peers":
    #     peers = result.get("peers", [])
    #     return ("peer_proposals", {"peers": peers}) if peers else (None, None)

    if tool_name == "list_pending":
        return "review_nudge", {"pending_count": result.get("count", 0)}

    return None, None


def _llm_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        timeout=60.0,  # 60s per LLM call - prevents hanging requests
    )


def _message_to_dict(msg: Any) -> dict:
    """Convert an OpenAI ChatCompletionMessage to a plain dict for storage."""
    d: dict[str, Any] = {"role": msg.role}
    if msg.content is not None:
        d["content"] = msg.content
    if getattr(msg, "tool_calls", None):
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d


def _parse_response(content: str) -> tuple[str, str | None, dict | None]:
    """Parse Claude's final message into (text, card_type, card_data).

    Handles three cases:
    - Raw JSON object (ideal)
    - JSON wrapped in ```json ... ``` code fence (common Claude behaviour)
    - Plain text fallback
    """
    import re

    if not content:
        return "", None, None

    stripped = content.strip()

    # 1. Try direct JSON parse
    try:
        parsed = json.loads(stripped)
        return parsed.get("message", ""), parsed.get("card_type"), parsed.get("card_data")
    except (json.JSONDecodeError, AttributeError):
        pass

    # 2. Extract JSON from ```json ... ``` code fence
    match = re.search(r"```json\s*([\s\S]*?)\s*```", stripped)
    if match:
        try:
            parsed = json.loads(match.group(1))
            return parsed.get("message", ""), parsed.get("card_type"), parsed.get("card_data")
        except (json.JSONDecodeError, AttributeError):
            pass

    # 3. Plain text - strip any code fences and return
    plain = re.sub(r"```[\s\S]*?```", "", stripped).strip()
    return plain, None, None


def run(
    message: str,
    conversation_id: str | None,
    user_id: str,
    user_name: str,
) -> dict[str, Any]:
    """Run the agent for one user turn.

    Returns:
        {
            "message": str,
            "card_type": str | None,
            "card_data": dict | None,
            "conversation_id": str,
        }
    """
    model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6")
    client = _llm_client()

    # Load or create conversation history
    conv_id, history = conv_model.get_or_create(conversation_id, user_id)

    # Inject user context so tools know who is performing actions
    user_ctx = f"[user_id={user_id} user_name={user_name}]"
    history.append({"role": "user", "content": f"{user_ctx}\n{message}"})

    final_text: str = ""
    card_type: str | None = None
    card_data: dict | None = None

    # Track the last card-bearing tool call so we can build the card without
    # asking Claude to reformat data it already received.
    last_card_tool: str | None = None
    last_card_result: str | None = None

    for iteration in range(MAX_TOOL_ITERATIONS):
        response = client.chat.completions.create(
            model=model,
            max_tokens=4096,
            temperature=0.2,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
        )

        choice = response.choices[0]
        assistant_msg = choice.message
        history.append(_message_to_dict(assistant_msg))

        if choice.finish_reason == "tool_calls" and assistant_msg.tool_calls:
            for tc in assistant_msg.tool_calls:
                args = json.loads(tc.function.arguments)
                log.info("Tool call: %s(%s)", tc.function.name, list(args.keys()))
                result = execute_tool(tc.function.name, args)
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
                if tc.function.name in _CARD_TOOLS:
                    last_card_tool = tc.function.name
                    last_card_result = result
        else:
            # Final response - derive card from tool result, Claude just writes the message
            final_text, _parsed_card_type, _parsed_card_data = _parse_response(
                assistant_msg.content or ""
            )
            if last_card_tool and last_card_result:
                card_type, card_data = _card_from_tool(last_card_tool, last_card_result)
            # Fall back to whatever Claude returned in case it ignored the prompt
            if card_type is None:
                card_type, card_data = _parsed_card_type, _parsed_card_data
            log.info("Agent finished after %d iteration(s) | card=%s", iteration + 1, card_type)
            break
    else:
        log.warning("Agent hit MAX_TOOL_ITERATIONS (%d)", MAX_TOOL_ITERATIONS)
        final_text = "I reached the maximum number of steps. Please try a simpler request."

    # Persist updated history
    conv_model.save(conv_id, history)

    return {
        "message": final_text,
        "card_type": card_type,
        "card_data": card_data,
        "conversation_id": conv_id,
    }
