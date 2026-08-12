"""LLM-based SEC filing classifier - single pass, no category, no novelty.

Mirrors classify_with_model()/validate_classification() from classifier.py but
for the filing schema (ticker, form_type, item_codes, fetched filing text).
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from pipeline.classifier import ALLOWED_MATERIALITY, classify_with_model, extract_json_object, norm

ALLOWED_SIGNAL = {'signal', 'weak_signal', 'noise'}
ALLOWED_ENTITY_TYPES = {'company', 'person', 'regulator', 'other'}
ALLOWED_EXTRACTION_QUALITY = {'full', 'partial', 'failed'}
SIGNAL_SCORE_THRESHOLD = 0.60
WEAK_SIGNAL_SCORE_THRESHOLD = 0.40

# 10-K/10-Q are always forced to signal_detection="signal" with signal_score
# fixed at FORCED_SIGNAL_SCORE - a deliberate scope decision, not a band
# boundary derived from content. Only 8-K uses the normal noise/weak_signal/
# signal band logic with a model-judged score. signal_score is a constant
# for periodic filings, not asked of the model or validated against its
# output - same discipline as deriving Novelty score deterministically
# elsewhere in this pipeline rather than trusting an LLM's freehand float.
# materiality and signal_reason are the ONLY fields that still vary and
# carry any distinction between a routine periodic filing and a major one.
FORCED_SIGNAL_FORM_TYPES = {'10-K', '10-Q'}
FORCED_SIGNAL_SCORE = 0.80

REQUIRED_FIELDS = (
    'signal_detection', 'signal_score', 'signal_reason', 'materiality',
    'already_disclosed', 'extraction_quality',
    'entities',
)

EXTRACTION_FAILED_RESULT = {
    'signal_detection': 'noise',
    'signal_score': 0.05,
    'signal_reason': (
        'Automated extraction could not locate the results-of-operations section '
        'in this filing; classification was not attempted against unreliable text. '
        'Needs manual review.'
    ),
    'materiality': 'none',
    'already_disclosed': False,
    'extraction_quality': 'failed',
    'entities': [],
}


def expected_signal_detection_for_score(signal_score: float) -> str:
    if signal_score >= SIGNAL_SCORE_THRESHOLD:
        return 'signal'
    if signal_score > WEAK_SIGNAL_SCORE_THRESHOLD:
        return 'weak_signal'
    return 'noise'


def validate_filing_classification(
    payload: dict[str, Any],
    *,
    form_type: str = '',
) -> dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ValueError(f'Missing fields: {", ".join(missing)}')

    signal_detection = norm(str(payload.get('signal_detection', '')))
    raw_signal_score = payload.get('signal_score')
    signal_reason = norm(str(payload.get('signal_reason', '')))
    materiality = norm(str(payload.get('materiality', '')))
    already_disclosed = payload.get('already_disclosed')
    extraction_quality = norm(str(payload.get('extraction_quality', '')))
    entities = payload.get('entities', [])

    if signal_detection not in ALLOWED_SIGNAL:
        raise ValueError(f'Invalid signal_detection: {signal_detection}')
    try:
        signal_score = float(raw_signal_score)
    except (TypeError, ValueError):
        raise ValueError(f'Invalid signal_score: {raw_signal_score}') from None
    if not math.isfinite(signal_score) or signal_score < 0.0 or signal_score > 1.0:
        raise ValueError(f'signal_score must be between 0 and 1: {signal_score}')

    if form_type in FORCED_SIGNAL_FORM_TYPES:
        if signal_detection != 'signal':
            raise ValueError(
                f'signal_detection must be "signal" for {form_type} filings: {signal_detection}'
            )
        # signal_score is a fixed constant for periodic filings, not the
        # model's own value - overwrite regardless of what was returned.
        signal_score = FORCED_SIGNAL_SCORE
    else:
        expected = expected_signal_detection_for_score(signal_score)
        if signal_detection != expected:
            raise ValueError(
                f'signal_detection must match score bands '
                f'noise<= {WEAK_SIGNAL_SCORE_THRESHOLD:.2f}, '
                f'weak_signal< {SIGNAL_SCORE_THRESHOLD:.2f}, '
                f'signal>= {SIGNAL_SCORE_THRESHOLD:.2f}: '
                f'{signal_detection} vs {signal_score}'
            )
    if not signal_reason:
        raise ValueError('signal_reason must be non-empty')
    if materiality not in ALLOWED_MATERIALITY:
        raise ValueError(f'Invalid materiality: {materiality}')
    if signal_detection == 'noise' and materiality != 'none':
        raise ValueError('materiality must be "none" when signal_detection is "noise"')
    if signal_detection in {'weak_signal', 'signal'} and materiality == 'none':
        raise ValueError('materiality must not be "none" when signal_detection is "weak_signal" or "signal"')

    if not isinstance(already_disclosed, bool):
        raise ValueError(f'already_disclosed must be a boolean: {already_disclosed!r}')
    if extraction_quality not in ALLOWED_EXTRACTION_QUALITY:
        raise ValueError(f'Invalid extraction_quality: {extraction_quality}')
    if extraction_quality == 'failed' and form_type not in FORCED_SIGNAL_FORM_TYPES and signal_detection != 'noise':
        raise ValueError('signal_detection must be "noise" when extraction_quality is "failed"')

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
        'already_disclosed': already_disclosed,
        'extraction_quality': extraction_quality,
        'entities': cleaned_entities,
    }


def build_filing_user_prompt(
    filing: dict[str, Any],
    filing_text: str,
    *,
    company_overview: dict[str, Any] | None = None,
) -> str:
    metadata = {
        'ticker': filing.get('ticker', ''),
        'cik': filing.get('cik', ''),
        'form_type': filing.get('form_type', ''),
        'item_codes': filing.get('item_codes', []),
        'filed_at': filing.get('filed_at', ''),
        'accepted_at': filing.get('accepted_at', ''),
        'period_of_report': filing.get('period_of_report', ''),
        'filer_category': filing.get('filer_category', ''),
        'accession_number': filing.get('accession_number', ''),
    }
    reference = company_overview or {}
    company_reference_data = {
        'annual_revenue': reference.get('revenue_ttm'),
        'market_capitalization': reference.get('market_cap'),
        'shares_outstanding': reference.get('shares_outstanding'),
    }

    import json
    prompt = 'Classify this SEC filing.\n\nFiling metadata:\n' + json.dumps(metadata, ensure_ascii=False, indent=2)
    prompt += '\n\nCompany reference data (use as denominator for materiality; null means unavailable - judge qualitatively and say so):\n'
    prompt += json.dumps(company_reference_data, ensure_ascii=False, indent=2)
    prompt += '\n\nFiling text:\n' + (filing_text or '(no text available)')
    prompt += '\n\nReturn strict JSON only.'
    return prompt


def classify_filing(
    filing: dict[str, Any],
    filing_text: str,
    *,
    system_prompt: str,
    models: list[str],
    api_key: str,
    base_url: str,
    timeout: int,
    max_attempts: int,
    extraction_found: bool = True,
    cache_system_prompt: bool = True,
    company_overview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """extraction_found=False (10-K/10-Q only, set by the caller from
    extract_results_section()'s second return value) skips the LLM call
    entirely and returns a fixed noise/needs-review result - classifying
    against unreliable fallback text (XBRL tag noise, front-matter) produces
    a confident-looking but ungrounded result, which is worse than flagging
    it honestly for manual review. This is the one case where a 10-K/10-Q
    result is allowed to be "noise" despite FORCED_SIGNAL_FORM_TYPES - no LLM
    call happened, so no real classification was made; this fallback means
    "unclassifiable", not "classified as unimportant".

    company_overview is the dict returned by adapters.news_client.get_company_overview()
    (market_cap, revenue_ttm, shares_outstanding, etc). Fetch once per ticker
    and pass the same dict into every filing classified for that ticker in a
    batch - these figures don't change filing-to-filing, no need to re-fetch
    per filing. None is a valid value (overview unavailable); the prompt is
    designed to judge qualitatively and say so, not fail, when this is absent.

    cache_system_prompt=True (default) marks the system prompt with an
    ephemeral cache breakpoint - unlike the news classifier, this prompt has
    no per-article dynamic example injection, so the ENTIRE system prompt is
    identical and cacheable on every single call, not just a static prefix.
    """
    if not extraction_found:
        return {
            **EXTRACTION_FAILED_RESULT,
            'ticker': filing.get('ticker', ''),
            'form_type': filing.get('form_type', ''),
            'item_codes': filing.get('item_codes', []),
            'accession_number': filing.get('accession_number', ''),
            'filed_at': filing.get('filed_at', ''),
        }

    form_type = filing.get('form_type', '')

    def _validator(payload: dict[str, Any]) -> dict[str, Any]:
        return validate_filing_classification(payload, form_type=form_type)

    user_prompt = build_filing_user_prompt(
        filing, filing_text,
        company_overview=company_overview,
    )
    errors: list[str] = []
    for model in models:
        for attempt in range(1, max_attempts + 1):
            try:
                result = classify_with_model(
                    system_prompt, user_prompt, model, api_key, base_url, timeout,
                    validator=_validator,
                    max_tokens=800,
                    cache_system_prompt=cache_system_prompt,
                    stage='sec_filing',
                    article_id=filing.get('accession_number'),
                )
                result['ticker'] = filing.get('ticker', '')
                result['form_type'] = filing.get('form_type', '')
                result['item_codes'] = filing.get('item_codes', [])
                result['accession_number'] = filing.get('accession_number', '')
                result['filed_at'] = filing.get('filed_at', '')
                return result
            except Exception as exc:
                errors.append(f'{model} attempt {attempt}: {exc}')
                time.sleep(0.25)
                continue
    raise RuntimeError('Filing classification failed: ' + ' | '.join(errors))


async def classify_filings_for_ticker(
    ticker: str,
    filings_with_text: list[tuple[dict[str, Any], str, bool]],
    *,
    system_prompt: str,
    models: list[str],
    api_key: str,
    base_url: str,
    timeout: int,
    max_attempts: int,
    cache_system_prompt: bool = True,
    get_company_overview_fn=None,
) -> list[dict[str, Any]]:
    """Classify every filing for one ticker, fetching company_overview ONCE
    and reusing it across all of them - revenue/market_cap/shares_outstanding
    don't change filing-to-filing within a batch, so there is no reason to
    re-fetch per filing. This is the fix for the gap where classify_filing()
    correctly ACCEPTS company_overview but nothing previously called it more
    than once per ticker in a real batch.

    filings_with_text: list of (filing_dict, filing_text_or_section, extraction_found)
    tuples - callers have already done the fetch_filing_text()/
    extract_results_section() step per filing before calling this.

    get_company_overview_fn: injected for testability (defaults to
    adapters.news_client.get_company_overview if not provided) - avoids a
    hard import-time dependency on the adapter for callers that want to pass
    a stub/mock.
    """
    if get_company_overview_fn is None:
        from adapters.news_client import get_company_overview as get_company_overview_fn

    overview = await get_company_overview_fn(ticker)

    results = []
    for filing, filing_text, extraction_found in filings_with_text:
        result = classify_filing(
            filing, filing_text,
            system_prompt=system_prompt,
            models=models,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_attempts=max_attempts,
            extraction_found=extraction_found,
            cache_system_prompt=cache_system_prompt,
            company_overview=overview,
        )
        results.append(result)
    return results


SEC_FILING_PROMPT_PATH = Path(__file__).parent.parent.parent / 'prompts' / 'sec_filing_classifier_v1.txt'


def load_sec_filing_prompt() -> str:
    text = SEC_FILING_PROMPT_PATH.read_text(encoding='utf-8')
    if not text.strip():
        raise ValueError(f'Prompt file is empty: {SEC_FILING_PROMPT_PATH}')
    return text
