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

    # 10-K/10-Q use the same noise/weak_signal/signal band logic as 8-K -
    # routing these form types to simulation regardless of score is the
    # caller's job (keyed on form_type, not signal_score); this validator
    # no longer special-cases them.
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
    if extraction_quality == 'failed' and signal_detection != 'noise':
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
    xbrl_facts: dict[str, Any] | None = None,
    exhibit_fetch_status: str = 'not_applicable',
    trailing_quarterly_revenue: list[dict[str, Any]] | None = None,
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
        'exhibit_fetch_status': exhibit_fetch_status,
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
    if xbrl_facts:
        prompt += (
            '\n\nExact reported financial figures for THIS filing (from SEC\'s own '
            'structured XBRL data, not extracted from the text below - use these '
            'values verbatim for any number you report; null means this filing did '
            'not tag that concept, not zero):\n'
        )
        prompt += json.dumps(xbrl_facts, ensure_ascii=False, indent=2)
    if trailing_quarterly_revenue:
        prompt += (
            '\n\nTrailing quarterly revenue for this company, oldest first, from SEC\'s '
            'own structured XBRL data (up to 8 quarters strictly before this filing\'s '
            'period_of_report). Use this to judge whether THIS quarter\'s growth is normal '
            'for this company or a real deviation - compute this quarter\'s YoY growth '
            '(from the revenue/revenue_prior_year block above), compute the average YoY '
            'growth across these trailing quarters, and band materiality on the DIFFERENCE '
            'between the two, not on the raw growth percentage alone. A company that '
            'consistently grows 60%+ every quarter is not "high" materiality for growing '
            '60% again; a company whose growth suddenly drops from a 60% trailing average '
            'to 12% is a real deceleration worth flagging even though 12% alone looks modest:\n'
        )
        prompt += json.dumps(trailing_quarterly_revenue, ensure_ascii=False, indent=2)
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
    xbrl_facts: dict[str, Any] | None = None,
    exhibit_fetch_status: str = 'not_applicable',
    trailing_quarterly_revenue: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """extraction_found=False (10-K/10-Q only, set by the caller from
    extract_results_section()'s second return value) skips the LLM call
    entirely and returns a fixed noise/needs-review result - classifying
    against unreliable fallback text (XBRL tag noise, front-matter) produces
    a confident-looking but ungrounded result, which is worse than flagging
    it honestly for manual review. No LLM call happened, so no real
    classification was made; this fallback means "unclassifiable", not
    "classified as unimportant".

    company_overview is the dict returned by adapters.news_client.get_company_overview()
    (market_cap, revenue_ttm, shares_outstanding, etc). Fetch once per ticker
    and pass the same dict into every filing classified for that ticker in a
    batch - these figures don't change filing-to-filing, no need to re-fetch
    per filing. None is a valid value (overview unavailable); the prompt is
    designed to judge qualitatively and say so, not fail, when this is absent.

    xbrl_facts (10-K/10-Q only) is adapters.sec_edgar.extract_xbrl_facts_for_filing()'s
    output - exact reported figures (revenue, EPS, dividends, ...) for this
    specific filing, from SEC's own structured data. Confirmed empirically
    this session: without this, the model can hallucinate plausible-looking
    but wrong figures from its training data (e.g. quoting a later fiscal
    year's dividend/buyback numbers for an earlier filing) rather than
    grounding strictly in the provided text. Passing exact figures explicitly
    removes the need for the model to recall or re-derive them from memory.

    exhibit_fetch_status ("full"/"partial"/"not_applicable", set by the caller
    from adapters.sec_edgar.fetch_filing_exhibits_text()'s second return value
    for 8-Ks with item codes 2.02/7.01/8.01) tells the model definitively
    whether the EX-99* exhibit appended to filing_text was actually fetched -
    without this, the model can only guess from context whether "no figures
    visible" means the exhibit is genuinely empty of them or the fetch failed,
    which the prompt otherwise has no way to distinguish.

    trailing_quarterly_revenue (10-K/10-Q only) is
    adapters.sec_edgar.get_trailing_quarterly_revenue()'s output - up to 8
    prior quarters of this company's own reported revenue. Lets the model
    judge THIS quarter's growth against the company's own recent trend
    instead of a fixed absolute-growth threshold - a fixed >10% band flags a
    consistently high-growth filer as permanently "high" for being normal,
    while missing the case where growth suddenly decelerates from a high
    baseline to something that still looks fine in isolation.

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
            'primary_doc_url': filing.get('primary_doc_url', ''),
        }

    form_type = filing.get('form_type', '')

    def _validator(payload: dict[str, Any]) -> dict[str, Any]:
        return validate_filing_classification(payload, form_type=form_type)

    user_prompt = build_filing_user_prompt(
        filing, filing_text,
        company_overview=company_overview,
        xbrl_facts=xbrl_facts,
        exhibit_fetch_status=exhibit_fetch_status,
        trailing_quarterly_revenue=trailing_quarterly_revenue,
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
                result['primary_doc_url'] = filing.get('primary_doc_url', '')
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
