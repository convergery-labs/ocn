"""LLM adapter: per-category summarisation using OpenRouter."""
import logging
from typing import Any

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

_SIGNAL_TIER_ORDER = {"signal": 0, "weak_signal": 1, "noise": 2}


def _client() -> OpenAI:
    return OpenAI(
        api_key=config.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )


def summarise_category(
    category: str,
    articles: list[dict[str, Any]],
) -> str:
    """Generate a 3-4 sentence investment-focused summary for a category.

    Uses signal tier, materiality, and novelty from agent classifications
    to weight the summary toward the most important articles.
    """
    # Sort: signal first (by score desc), then weak_signal, then noise
    top = sorted(
        articles,
        key=lambda a: (
            _SIGNAL_TIER_ORDER.get(a.get("signal_detection", "noise"), 2),
            -float(a.get("signal_score") or 0),
        ),
    )[:10]

    article_lines = []
    for a in top:
        title = a.get("title") or a.get("url", "")
        tier = a.get("signal_detection", "noise")
        score = float(a.get("signal_score") or 0)
        materiality = a.get("materiality", "")
        novelty = a.get("novelty") or ""
        entities = [e.get("name", "") for e in (a.get("entities") or [])]
        entity_str = f" [{', '.join(entities[:3])}]" if entities else ""
        novelty_str = f" novelty={novelty}" if novelty else ""
        article_lines.append(
            f'- "{title}"{entity_str} '
            f"({tier}, score={score:.2f}, materiality={materiality}{novelty_str})"
        )

    prompt = (
        f'Write a 3-4 sentence investment-focused summary for the category '
        f'{category} based on these articles. '
        f"Prioritise signal-tier articles with high materiality and step_change novelty. "
        f"Be concise and factual.\n\n"
        f"Articles:\n" + "\n".join(article_lines)
    )

    client = _client()
    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()
