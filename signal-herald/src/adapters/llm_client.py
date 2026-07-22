"""LLM adapter: per-category summarisation using OpenRouter."""
import json
import logging
import re
from typing import Any

from openai import OpenAI

import config

logger = logging.getLogger(__name__)

_SIGNAL_TIER_ORDER = {"signal": 0, "weak_signal": 1, "noise": 2}

# Matches straight, curly, and backtick quotes
_QUOTE_CHARS = r'["“”‘’`\']'


def _client() -> OpenAI:
    return OpenAI(
        api_key=config.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )


def group_duplicate_stories(articles: list[dict[str, Any]]) -> list[int]:
    """Return the indices of `articles` to keep, one per underlying real-world
    event. Different outlets often rewrite the same story with different
    wording (e.g. "went rogue" vs "broke loose" vs "escaped containment" for
    the same incident) which entity/keyword overlap can't reliably tell apart
    from genuinely distinct stories, so an LLM call clusters them instead.
    `articles` is assumed pre-sorted best-first; the first (highest-scoring)
    index in each cluster is kept. Falls back to keeping everything on any
    LLM/parsing failure.
    """
    if len(articles) <= 1:
        return list(range(len(articles)))

    lines = []
    for i, a in enumerate(articles):
        title = a.get("title") or a.get("url", "")
        entities = [e.get("name", "") for e in (a.get("entities") or [])]
        entity_str = f" [{', '.join(entities[:4])}]" if entities else ""
        lines.append(f"{i}: {title}{entity_str}")

    prompt = (
        "These are news headlines about AI-economy events, possibly from different "
        "outlets covering the same underlying event with different wording.\n\n"
        "Group the indices below into clusters where every index in a cluster "
        "describes the same specific real-world event (e.g. the same deal, the same "
        "incident, the same announcement) — not just the same company or topic. "
        "Distinct events involving the same company must NOT be grouped together.\n\n"
        "Headlines:\n" + "\n".join(lines) + "\n\n"
        'Return strict JSON only: {"groups": [[0, 3, 7], [1], [2, 4], ...]} '
        "where every index 0.." + str(len(articles) - 1) + " appears exactly once across all groups."
    )

    try:
        client = _client()
        response = client.chat.completions.create(
            model=config.OPENROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        text = (response.choices[0].message.content or "").strip()
        fenced = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.S)
        if fenced:
            text = fenced.group(1)
        start, end = text.find("{"), text.rfind("}")
        groups = json.loads(text[start:end + 1])["groups"]

        seen: set[int] = set()
        keep: list[int] = []
        for group in groups:
            valid = [i for i in group if isinstance(i, int) and 0 <= i < len(articles) and i not in seen]
            if not valid:
                continue
            seen.update(valid)
            keep.append(min(valid))
        missing = [i for i in range(len(articles)) if i not in seen]
        keep.extend(missing)
        return sorted(keep)
    except Exception:
        logger.warning("group_duplicate_stories failed; keeping all articles", exc_info=True)
        return list(range(len(articles)))


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
        f"Be concise and factual. Do not quote or wrap any category name in quotation marks.\n\n"
        f"Articles:\n" + "\n".join(article_lines)
    )

    client = _client()
    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    text = (response.choices[0].message.content or "").strip()
    # Strip quotes around any known category name in the summary
    for cat in config.CATEGORIES:
        escaped = re.escape(cat)
        text = re.sub(rf'{_QUOTE_CHARS}{escaped}{_QUOTE_CHARS}', cat, text)
    return text
