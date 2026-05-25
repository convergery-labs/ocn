"""LLM-based signal classifier — base pass + optional STORM-style second pass."""
from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ALLOWED_SIGNAL = {'signal', 'weak_signal', 'noise'}
ALLOWED_MATERIALITY = {'high', 'medium', 'low', 'none'}
SIGNAL_SCORE_THRESHOLD = 0.60
WEAK_SIGNAL_SCORE_THRESHOLD = 0.40
ALLOWED_NOVELTY = {'step_change', 'meaningful_update', 'incremental_update', 'repeated_coverage'}
ALLOWED_CONFIDENCE = {'high', 'medium', 'low'}
ALLOWED_CATEGORIES = {
    'Minerals & Raw Materials',
    'Energy',
    'Semiconductor Manufacturing',
    'Computer Hardware',
    'Thermal & Cooling',
    'Data Center Infrastructure',
    'Cloud & Compute Market',
    'Software / Infrastructure',
    'AI Data',
    'AI Models',
    'Applications & Economy',
}
ALLOWED_ENTITY_TYPES = {
    'company',
    'model_product',
    'product',
    'event',
    'regulator',
    'person',
    'country_region',
    'platform',
    'benchmark',
    'facility',
    'other',
}

REQUIRED_FIELDS = (
    'signal_detection',
    'signal_score',
    'signal_reason',
    'materiality',
    'category',
    'entities',
)
CONTENT_MODES = {'full', 'summary', 'smart'}
SMART_SUMMARY_MIN_CHARS = 220


def has_usable_body(article: dict[str, Any]) -> bool:
    body = article.get('body')
    if not isinstance(body, str):
        return False
    return bool(norm(body))


def norm(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip())


def extract_json_object(text: str) -> dict[str, Any]:
    value = (text or '').strip()
    if not value:
        return {}
    fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', value, re.S)
    if fenced:
        value = fenced.group(1)
    start = value.find('{')
    end = value.rfind('}')
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        parsed = json.loads(value[start:end + 1])
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_prompt(path: Path) -> str:
    text = path.read_text(encoding='utf-8')
    if not text.strip():
        raise ValueError(f'Prompt file is empty: {path}')
    return text


def _normalized_summary(article: dict[str, Any]) -> str:
    summary = article.get('summary')
    return norm(summary) if isinstance(summary, str) else ''


def _should_include_body(article: dict[str, Any], content_mode: str) -> bool:
    if content_mode == 'full':
        return True
    if content_mode == 'summary':
        return False
    if content_mode != 'smart':
        raise ValueError(f'Unsupported content_mode: {content_mode}')
    summary = _normalized_summary(article)
    return len(summary) < SMART_SUMMARY_MIN_CHARS


def build_article_payload(article: dict[str, Any], *, content_mode: str = 'smart') -> dict[str, Any]:
    if content_mode not in CONTENT_MODES:
        raise ValueError(f'Unsupported content_mode: {content_mode}')
    payload = {
        'id': article.get('id'),
        'run_id': article.get('run_id'),
        'url': article.get('url', ''),
        'title': article.get('title', ''),
        'summary': article.get('summary', ''),
        'source': article.get('source', ''),
        'published': article.get('published', ''),
        'domain': article.get('domain', ''),
        'content_mode': content_mode,
    }
    if _should_include_body(article, content_mode) and has_usable_body(article):
        payload['body'] = article.get('body', '')
    return payload


def build_user_prompt(
    article: dict[str, Any],
    *,
    category_hints: list[dict[str, Any]] | None = None,
    content_mode: str = 'smart',
) -> str:
    payload = build_article_payload(article, content_mode=content_mode)
    prompt = 'Classify this article.\n\nArticle:\n' + json.dumps(payload, ensure_ascii=False, indent=2)
    if category_hints:
        prompt += '\n\nRouting hints (for category shortlist only, not final rules):\n' + json.dumps(category_hints[:3], ensure_ascii=False, indent=2)
    prompt += '\n\nReturn strict JSON only.'
    return prompt


def expected_signal_detection_for_score(signal_score: float) -> str:
    if signal_score >= SIGNAL_SCORE_THRESHOLD:
        return 'signal'
    if signal_score > WEAK_SIGNAL_SCORE_THRESHOLD:
        return 'weak_signal'
    return 'noise'


def validate_classification(payload: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ValueError(f'Missing fields: {", ".join(missing)}')

    signal_detection = norm(str(payload.get('signal_detection', '')))
    raw_signal_score = payload.get('signal_score')
    materiality = norm(str(payload.get('materiality', '')))
    category = norm(str(payload.get('category', '')))
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
    expected_signal_detection = expected_signal_detection_for_score(signal_score)
    if signal_detection != expected_signal_detection:
        raise ValueError(
            f'signal_detection must match score bands '
            f'noise<= {WEAK_SIGNAL_SCORE_THRESHOLD:.2f}, '
            f'weak_signal< {SIGNAL_SCORE_THRESHOLD:.2f}, '
            f'signal>= {SIGNAL_SCORE_THRESHOLD:.2f}: '
            f'{signal_detection} vs {signal_score}'
        )
    if materiality not in ALLOWED_MATERIALITY:
        raise ValueError(f'Invalid materiality: {materiality}')
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f'Invalid category: {category}')
    if signal_detection == 'noise' and materiality != 'none':
        raise ValueError('materiality must be "none" when signal_detection is "noise"')
    if signal_detection in {'weak_signal', 'signal'} and materiality == 'none':
        raise ValueError('materiality must not be "none" when signal_detection is "weak_signal" or "signal"')
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
        'signal_reason': signal_reason,
        'materiality': materiality,
        'category': category,
        'entities': cleaned_entities,
    }


def classify_with_model(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
    base_url: str,
    timeout: int,
    *,
    validator=None,
) -> dict[str, Any]:
    if validator is None:
        validator = validate_classification
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    request_payload = {
        'model': model,
        'temperature': 0,
        'seed': 42,
        'max_tokens': 1200,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
    }
    req = Request(
        f'{base_url}/chat/completions',
        data=json.dumps(request_payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode('utf-8', errors='ignore'))
    content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
    if isinstance(content, list):
        content = ''.join(part.get('text', '') for part in content if isinstance(part, dict))
    parsed = extract_json_object(content)
    if not parsed:
        raise ValueError('Model returned non-JSON or empty JSON response')
    return validator(parsed)


def classify_article(
    article: dict[str, Any],
    *,
    system_prompt: str,
    models: list[str],
    api_key: str,
    base_url: str,
    timeout: int,
    max_attempts: int,
    category_hints: list[dict[str, Any]] | None = None,
    content_mode: str = 'smart',
) -> dict[str, Any]:
    user_prompt = build_user_prompt(article, category_hints=category_hints, content_mode=content_mode)
    errors: list[str] = []
    for model in models:
        for attempt in range(1, max_attempts + 1):
            try:
                result = classify_with_model(system_prompt, user_prompt, model, api_key, base_url, timeout)
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
    raise RuntimeError('Classification failed: ' + ' | '.join(errors))


def validate_classification_v2(payload: dict[str, Any]) -> dict[str, Any]:
    """Extend validate_classification with novelty and confidence field checks."""
    base = validate_classification(payload)

    novelty = norm(str(payload.get('novelty', '')))
    if novelty not in ALLOWED_NOVELTY:
        raise ValueError(f'Invalid novelty: {novelty}')

    novelty_basis = norm(str(payload.get('novelty_basis', '')))
    if not novelty_basis:
        raise ValueError('novelty_basis must be non-empty')

    confidence = norm(str(payload.get('confidence', '')))
    if confidence not in ALLOWED_CONFIDENCE:
        raise ValueError(f'Invalid confidence: {confidence}')

    confidence_basis = norm(str(payload.get('confidence_basis', '')))
    if not confidence_basis:
        raise ValueError('confidence_basis must be non-empty')

    refinement_reason = norm(str(payload.get('refinement_reason', '')))
    if not refinement_reason:
        raise ValueError('refinement_reason must be non-empty')

    return {
        **base,
        'novelty': novelty,
        'novelty_basis': novelty_basis,
        'confidence': confidence,
        'confidence_basis': confidence_basis,
        'refinement_reason': refinement_reason,
    }


def build_user_prompt_v2(
    article: dict[str, Any],
    *,
    base_result: dict[str, Any],
    entity_history: list[dict[str, Any]],
    web_snippets: list[dict[str, Any]],
    batch_context: list[dict[str, Any]] | None = None,
    content_mode: str = 'smart',
) -> str:
    payload = build_article_payload(article, content_mode=content_mode)
    parts = [
        'Refine the classification of this article using the provided context.\n\n'
        'Article:\n' + json.dumps(payload, ensure_ascii=False, indent=2),
        '\n\nBase classification:\n' + json.dumps(base_result, ensure_ascii=False, indent=2),
        '\n\nEntity history (recent signal/weak_signal rows, same entities):\n'
        + json.dumps(entity_history or [], ensure_ascii=False, indent=2),
        '\n\nWeb search snippets:\n'
        + json.dumps(web_snippets or [], ensure_ascii=False, indent=2),
        '\n\nOther articles in this news batch (titles only):\n'
        + json.dumps(batch_context or [], ensure_ascii=False, indent=2),
        '\n\nReturn strict JSON only.',
    ]
    return ''.join(parts)


def classify_article_two_stage(
    article: dict[str, Any],
    *,
    system_prompt_v1: str,
    system_prompt_v2: str,
    entity_history_fn,
    web_search_fn,
    models: list[str],
    api_key: str,
    base_url: str,
    timeout: int,
    max_attempts: int,
    category_hints: list[dict[str, Any]] | None = None,
    content_mode: str = 'smart',
    batch_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    # Stage 1: base pass (existing logic unchanged)
    base = classify_article(
        article,
        system_prompt=system_prompt_v1,
        models=models,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_attempts=max_attempts,
        category_hints=category_hints,
        content_mode=content_mode,
    )
    base_signal_detection = base['signal_detection']
    base_signal_score = base['signal_score']

    if base_signal_detection == 'noise':
        return {
            **base,
            'base_signal_detection': base_signal_detection,
            'base_signal_score': base_signal_score,
            'novelty': None,
            'novelty_basis': None,
            'confidence': None,
            'confidence_basis': None,
            'refinement_reason': None,
        }

    # Stage 2: gather context concurrently (DB history + web search)
    entity_names = [e['name'] for e in base.get('entities', [])]
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_history = ex.submit(entity_history_fn, entity_names)
        f_web = ex.submit(web_search_fn, entity_names[:2], base.get('signal_reason', ''))
    history = f_history.result()
    web_snips = f_web.result()  # [] on any failure — second pass still runs

    # Stage 2: refined classification
    user_prompt = build_user_prompt_v2(
        article,
        base_result=base,
        entity_history=history,
        web_snippets=web_snips,
        batch_context=batch_context,
        content_mode=content_mode,
    )
    errors: list[str] = []
    for model in models:
        for attempt in range(1, max_attempts + 1):
            try:
                final = classify_with_model(
                    system_prompt_v2,
                    user_prompt,
                    model,
                    api_key,
                    base_url,
                    timeout,
                    validator=validate_classification_v2,
                )
                final['id'] = article.get('id')
                if article.get('run_id') is not None:
                    final['run_id'] = article.get('run_id')
                final['url'] = article.get('url', '')
                final['headline'] = article.get('title', '')
                return {
                    **final,
                    'base_signal_detection': base_signal_detection,
                    'base_signal_score': base_signal_score,
                }
            except Exception as exc:
                errors.append(f'{model} attempt {attempt}: {exc}')
                time.sleep(0.25)
                continue

    # Second pass failed — fall back to base with null novelty/confidence
    return {
        **base,
        'base_signal_detection': base_signal_detection,
        'base_signal_score': base_signal_score,
        'novelty': None,
        'novelty_basis': None,
        'confidence': None,
        'confidence_basis': None,
        'refinement_reason': None,
    }
