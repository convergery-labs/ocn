"""LLM-based geopolitical/macro news classifier - single pass, no category, no materiality.

Mirrors classify_with_model()/validate_classification() from classifier.py and
filing_classifier.py's shape, but for the geopolitical schema (concreteness +
economic_scale sub-scores, no category/materiality/novelty).
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from pipeline.classifier import build_user_prompt, classify_with_model, norm

ALLOWED_SIGNAL = {'signal', 'weak_signal', 'noise'}
ALLOWED_ENTITY_TYPES = {'country_region', 'person', 'government_body', 'organization', 'other'}
SIGNAL_SCORE_THRESHOLD = 0.60
WEAK_SIGNAL_SCORE_THRESHOLD = 0.40

REQUIRED_FIELDS = (
    'signal_detection', 'signal_score', 'concreteness', 'economic_scale',
    'signal_reason', 'entities',
)


def expected_signal_detection_for_score(signal_score: float) -> str:
    if signal_score >= SIGNAL_SCORE_THRESHOLD:
        return 'signal'
    if signal_score > WEAK_SIGNAL_SCORE_THRESHOLD:
        return 'weak_signal'
    return 'noise'


def validate_geopolitical_classification(payload: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ValueError(f'Missing fields: {", ".join(missing)}')

    signal_detection = norm(str(payload.get('signal_detection', '')))
    raw_signal_score = payload.get('signal_score')
    raw_concreteness = payload.get('concreteness')
    raw_economic_scale = payload.get('economic_scale')
    signal_reason = norm(str(payload.get('signal_reason', '')))
    entities = payload.get('entities', [])

    if signal_detection not in ALLOWED_SIGNAL:
        raise ValueError(f'Invalid signal_detection: {signal_detection}')

    try:
        signal_score = float(raw_signal_score)
    except (TypeError, ValueError):
        raise ValueError(f'Invalid signal_score: {raw_signal_score}') from None
    if not math.isfinite(signal_score) or signal_score < 0.0 or signal_score > 1.0:
        raise ValueError(f'signal_score must be between 0 and 1: {signal_score}')

    expected = expected_signal_detection_for_score(signal_score)
    if signal_detection != expected:
        raise ValueError(
            f'signal_detection must match score bands '
            f'noise<= {WEAK_SIGNAL_SCORE_THRESHOLD:.2f}, '
            f'weak_signal< {SIGNAL_SCORE_THRESHOLD:.2f}, '
            f'signal>= {SIGNAL_SCORE_THRESHOLD:.2f}: '
            f'{signal_detection} vs {signal_score}'
        )

    try:
        concreteness = float(raw_concreteness)
    except (TypeError, ValueError):
        raise ValueError(f'Invalid concreteness: {raw_concreteness}') from None
    if not math.isfinite(concreteness) or concreteness < 0.0 or concreteness > 1.0:
        raise ValueError(f'concreteness must be between 0 and 1: {concreteness}')

    try:
        economic_scale = float(raw_economic_scale)
    except (TypeError, ValueError):
        raise ValueError(f'Invalid economic_scale: {raw_economic_scale}') from None
    if not math.isfinite(economic_scale) or economic_scale < 0.0 or economic_scale > 1.0:
        raise ValueError(f'economic_scale must be between 0 and 1: {economic_scale}')

    if not signal_reason:
        raise ValueError('signal_reason must be non-empty')
    if not isinstance(entities, list):
        raise ValueError('entities must be a list')

    cleaned_entities: list[dict[str, str]] = []
    for item in entities:
        if not isinstance(item, dict):
            raise ValueError('entities must be a list of objects with name and type')
        name = norm(str(item.get('name', '')))
        entity_type = norm(str(item.get('type', '')))
        if not name:
            raise ValueError('entity name must be non-empty')
        if entity_type not in ALLOWED_ENTITY_TYPES:
            entity_type = 'other'
        cleaned_entities.append({'name': name, 'type': entity_type})

    return {
        'signal_detection': signal_detection,
        'signal_score': round(signal_score, 4),
        'concreteness': round(concreteness, 4),
        'economic_scale': round(economic_scale, 4),
        'signal_reason': signal_reason,
        'entities': cleaned_entities,
    }


def classify_geopolitical_article(
    article: dict[str, Any],
    *,
    system_prompt: str,
    models: list[str],
    api_key: str,
    base_url: str,
    timeout: int,
    max_attempts: int,
    content_mode: str = 'smart',
    cache_system_prompt: bool = True,
) -> dict[str, Any]:
    """Single-pass classification against the geopolitical prompt.

    cache_system_prompt=True (default) marks the system prompt with an
    ephemeral cache breakpoint - like filing_classifier.py, this prompt has no
    per-article dynamic example injection (only 9 examples total, unlike the
    75-example AI-universe prompt), so the entire system prompt is identical
    and cacheable on every call.
    """
    user_prompt = build_user_prompt(article, content_mode=content_mode)
    errors: list[str] = []
    for model in models:
        for attempt in range(1, max_attempts + 1):
            try:
                result = classify_with_model(
                    system_prompt, user_prompt, model, api_key, base_url, timeout,
                    validator=validate_geopolitical_classification,
                    max_tokens=800,
                    cache_system_prompt=cache_system_prompt,
                    stage='geopolitical',
                    article_id=article.get('id'),
                )
                result['id'] = article.get('id')
                if article.get('run_id') is not None:
                    result['run_id'] = article.get('run_id')
                result['url'] = article.get('url', '')
                result['headline'] = article.get('title', '')
                return result
            except Exception as exc:
                errors.append(f'{model} attempt {attempt}: {exc}')
                time.sleep(0.25)
                continue
    raise RuntimeError('Geopolitical classification failed: ' + ' | '.join(errors))


GEOPOLITICAL_PROMPT_PATH = Path(__file__).parent.parent.parent / 'prompts' / 'geopolitical_classifier_v1.txt'


def load_geopolitical_prompt() -> str:
    text = GEOPOLITICAL_PROMPT_PATH.read_text(encoding='utf-8')
    if not text.strip():
        raise ValueError(f'Prompt file is empty: {GEOPOLITICAL_PROMPT_PATH}')
    return text
