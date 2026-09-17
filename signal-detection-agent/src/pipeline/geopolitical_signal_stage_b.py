"""Stage B: single Haiku-class model call - talk or action? - for
geopolitical_signal articles that survived Stage A's free filters
(signal_detection='waiting').

One call per headline, one word out (HIGH/WEAK), no retry - same shape and
cost-safety reasoning as taiwan_signal_classifier.py's
_classify_gdelt_relevance: failing toward WEAK (hiding a possible signal)
is the safer default than failing toward HIGH (surfacing noise as if it
were checked). Raw HTTP via urllib.request against this service's existing
OpenAI-compatible endpoint, same as every other model call in this service
- no openai SDK dependency.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "geopolitical_signal_stage_b_v1.txt"

_VALID_ANSWERS = frozenset({"HIGH", "WEAK"})


def load_stage_b_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def classify_geopolitical_signal_headline(
    title: str,
    *,
    system_prompt: str,
    model: str,
    api_key: str,
    base_url: str,
    timeout: int,
) -> str:
    """Return exactly "HIGH" or "WEAK" for one headline.

    Strict validation, no retry: any response that is not the literal
    string "HIGH" or "WEAK" (extra text, wrong case after normalization,
    an empty response, a request error) is treated as WEAK - per the
    spec's own reasoning, a repair attempt costs more than the value of
    one extra try on a call this cheap, and hiding a possible signal is
    the safer failure direction than surfacing noise as checked.
    """
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 5,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Headline: {title}"},
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
        answer = (content or "").strip().upper()
        if answer in _VALID_ANSWERS:
            return answer
        logger.warning(
            "[GEOPOLITICAL_SIGNAL_STAGE_B] unrecognized response, defaulting"
            " to WEAK: %r", content,
        )
        return "WEAK"
    except Exception as exc:
        logger.warning(
            "[GEOPOLITICAL_SIGNAL_STAGE_B] classification failed, defaulting"
            " to WEAK: %s", exc,
        )
        return "WEAK"
