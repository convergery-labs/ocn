"""LLM adapter: batch classify discovery candidates via OpenRouter."""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

_CATEGORY_LIST = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(config.CATEGORIES))


def _client() -> OpenAI:
    """Return an OpenAI-compatible client pointed at OpenRouter."""
    return OpenAI(
        api_key=config.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )


def classify_batch(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify a batch of up to 10 rows.

    Each row dict should contain: company_name, source_description, page_summary,
    ticker, exchange, country_market.

    Returns a list of classification dicts in the same order as input.
    On failure, affected rows get {"decision": "error", "reason": "<message>"}.
    """
    if not rows:
        return []

    company_lines = []
    for i, r in enumerate(rows):
        parts = [f"{i + 1}. {r.get('company_name', 'Unknown')}"]
        if r.get("ticker"):
            parts.append(f"   Ticker: {r['ticker']} ({r.get('exchange', '')})")
        if r.get("country_market"):
            parts.append(f"   Country/Market: {r['country_market']}")
        description = r.get("page_summary") or r.get("source_description") or ""
        if description:
            parts.append(f"   Description: {description[:500]}")
        company_lines.append("\n".join(parts))

    prompt = (
        "Classify each company below for inclusion in an AI investment universe.\n\n"
        f"Categories:\n{_CATEGORY_LIST}\n\n"
        "For each company return:\n"
        '- decision: "Add" or "Skip"\n'
        "- category: one of the 11 categories (only when decision=Add)\n"
        "- subcategory: short free-text label (only when decision=Add)\n"
        '- company_type: "Public" or "Private / Non-public"\n'
        '- universe_type: "US Public / ADR", "International Public", or "Private / Strategic Watchlist"\n'
        "- reason: one sentence explanation\n\n"
        f"Companies:\n{chr(10).join(company_lines)}\n\n"
        'Return a JSON object with key "classifications" — an array in the same order as the input.'
    )

    client = _client()
    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = response.choices[0].message.content or "{}"
    try:
        classifications = json.loads(raw).get("classifications", [])
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON for classify_batch")
        return [{"decision": "error", "reason": "invalid JSON from LLM"}] * len(rows)

    result = []
    for i in range(len(rows)):
        if i < len(classifications):
            result.append(classifications[i])
        else:
            logger.warning("LLM returned fewer classifications than expected (row %d)", i)
            result.append({"decision": "error", "reason": "missing from LLM response"})
    return result
