"""Stage C, Layer 2: one model call per HIGH article - channel, actors,
assets, impacted_categories, one_line.

Same raw-HTTP-via-urllib pattern as Stage B (pipeline/geopolitical_signal_
stage_b.py) - no openai SDK dependency, consistent with every other model
call in this service.

Fail-open on any parse/validation failure: per the spec, "any JSON parse
failure stores the item as HIGH with null tags rather than dropping it" -
a tagging failure must never delete or hide a real signal. This module
never raises for a malformed model response; callers get back a dict with
every field set to None on failure, same shape as a successful parse.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.request import Request, urlopen

from pipeline.categories import ALLOWED_CATEGORIES
from pipeline.classifier import extract_json_object

logger = logging.getLogger(__name__)

_VALID_CHANNELS = frozenset({"energy", "trade", "sanctions", "shipping", "conflict"})
_VALID_ASSETS = frozenset({
    "crude_oil", "natural_gas", "gold", "usd", "treasuries",
    "semis", "defense", "shipping_freight", "autos",
    "agriculture", "broad_equities",
})

_EMPTY_RESULT: dict[str, Any] = {
    "channel": None,
    "actors": None,
    "assets": None,
    "impacted_categories": None,
    "one_line": None,
}

# Body is supporting context for a still-short headline-classification task,
# not the full-article-comprehension job classifier.py's main pipeline does
# - capped well below that pipeline's limits to keep Layer 2's per-article
# cost close to its original headline-only size.
_MAX_BODY_CHARS = 2000


def _validate(parsed: Any) -> dict[str, Any] | None:
    """Return a cleaned result dict, or None if the shape/values are
    unusable. Unrecognized values inside otherwise-valid arrays are
    dropped individually (not treated as a whole-response failure) - a
    model inventing one bad asset name shouldn't discard three good ones.
    """
    if not isinstance(parsed, dict):
        return None

    channel = parsed.get("channel")
    if channel not in _VALID_CHANNELS:
        channel = None

    actors = parsed.get("actors")
    if not isinstance(actors, list):
        actors = None
    else:
        actors = [a for a in actors if isinstance(a, str) and a.strip()]

    assets = parsed.get("assets")
    if not isinstance(assets, list):
        assets = None
    else:
        assets = [a for a in assets if a in _VALID_ASSETS]

    impacted_categories = parsed.get("impacted_categories")
    if not isinstance(impacted_categories, list):
        impacted_categories = None
    else:
        impacted_categories = [
            c for c in impacted_categories if c in ALLOWED_CATEGORIES
        ]

    one_line = parsed.get("one_line")
    if not isinstance(one_line, str) or not one_line.strip():
        one_line = None

    return {
        "channel": channel,
        "actors": actors,
        "assets": assets,
        "impacted_categories": impacted_categories,
        "one_line": one_line,
    }


def classify_geopolitical_signal_tags(
    title: str,
    *,
    body: str | None = None,
    system_prompt: str,
    model: str,
    api_key: str,
    base_url: str,
    timeout: int,
) -> dict[str, Any]:
    """Return {channel, actors, assets, impacted_categories, one_line}.

    ``body`` is optional article text (news-retrieval may not have it, or
    the fetch may have failed/404'd upstream by the time this runs) - when
    present it's included as extra context after the headline, truncated
    to _MAX_BODY_CHARS, so the model can name the specific goods/sector an
    intentionally terse headline leaves out (see the prompt's own
    empty-impacted_categories rule for why that distinction matters). When
    absent, the call degrades to the original headline-only prompt.

    Any failure (network error, non-JSON response, wrong shape, timeout)
    returns all-None fields rather than raising - the caller still writes
    the row as HIGH, just without tags, per the spec's fail-open rule.
    """
    user_content = f"Headline: {title}"
    if body:
        user_content += f"\n\nArticle text: {body[:_MAX_BODY_CHARS]}"
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        req = Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        # confirmed live: this model wraps its JSON in a ```json ... ```
        # markdown fence despite the prompt saying "Return ONLY a JSON
        # object" - extract_json_object (pipeline/classifier.py) already
        # handles this exact case (fence-stripping + brace-boundary
        # extraction), reused here rather than duplicating that logic.
        parsed = extract_json_object(content)
        if not parsed:
            raise ValueError(f"no JSON object found in response: {content!r}")
    except Exception as exc:
        logger.warning(
            "[GEOPOLITICAL_SIGNAL_STAGE_C] Layer 2 tagging failed, storing"
            " HIGH with null tags: %s", exc,
        )
        return dict(_EMPTY_RESULT)

    validated = _validate(parsed)
    if validated is None:
        logger.warning(
            "[GEOPOLITICAL_SIGNAL_STAGE_C] Layer 2 response had an"
            " unusable shape, storing HIGH with null tags: %r", parsed,
        )
        return dict(_EMPTY_RESULT)
    return validated
