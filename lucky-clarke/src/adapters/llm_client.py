"""LLM adapter: article categorisation and per-category summarisation."""
import json
import logging
from typing import Any

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

_CATEGORY_LIST = "\n".join(
    f"{i + 1}. {c}" for i, c in enumerate(config.CATEGORIES)
)


def _client() -> OpenAI:
    """Return an OpenAI-compatible client pointed at OpenRouter."""
    return OpenAI(
        api_key=config.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )


def categorise_articles(
    articles: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Assign each article to one of CATEGORIES; return category → articles.

    Articles: list of {url, title, label, composite_score}.
    Articles that don't fit any category are silently dropped.
    """
    if not articles:
        return {}

    article_lines = "\n".join(
        f'{i}. "{a.get("title", a["url"])}"'
        for i, a in enumerate(articles)
    )
    prompt = (
        "You are classifying AI/tech news articles into investment "
        "research categories.\n\n"
        f"Categories:\n{_CATEGORY_LIST}\n\n"
        f"Articles:\n{article_lines}\n\n"
        "Return a JSON object mapping each article index (as a string) "
        'to the exact category name, or "Other" if none fits. '
        "Example: {\"0\": \"Quantum and Advanced Compute\", \"1\": "
        '"Other"}'
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
        mapping: dict[str, str] = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM returned invalid JSON for categorisation")
        return {}

    result: dict[str, list[dict[str, Any]]] = {}
    for idx_str, category in mapping.items():
        if category == "Other" or category not in config.CATEGORIES:
            continue
        try:
            article = articles[int(idx_str)]
        except (ValueError, IndexError):
            continue
        result.setdefault(category, []).append(article)
    return result


def summarise_category(
    category: str,
    articles: list[dict[str, Any]],
) -> str:
    """Generate a 3-4 sentence summary for a category.

    articles sorted by composite_score descending before calling;
    top 10 are passed to the LLM.
    """
    top = sorted(
        articles, key=lambda a: a.get("composite_score", 0), reverse=True
    )[:10]
    article_lines = "\n".join(
        f'- "{a.get("title", a["url"])}" '
        f'(score: {a.get("composite_score", 0):.2f})'
        for a in top
    )
    prompt = (
        f'Write a 3-4 sentence investment-focused summary for the '
        f'category "{category}" based on these articles. '
        f"Weight higher-scoring articles more heavily. "
        f"Be concise and factual.\n\n"
        f"Articles:\n{article_lines}"
    )

    client = _client()
    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return (response.choices[0].message.content or "").strip()
