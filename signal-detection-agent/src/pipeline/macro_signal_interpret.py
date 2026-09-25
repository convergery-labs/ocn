"""INTERPRET (spec section 8): one LLM call per collapsed event, using the
Appendix A system prompt verbatim. Follows this codebase's own convention
(classifier.py): prompt-only JSON instruction, regex/brace-slice JSON
extraction (classify_with_model's own extract_json_object), code-side
validation - no response_format/JSON-schema enforcement param, matching
every other LLM call in this repo.

Validated standalone (schema/banned-language rules, prompt content) before
being ported into this service - see project plan history.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import config
from pipeline.classifier import classify_with_model
from pipeline.macro_signal_factcheck import check_transmission_matches_real_numbers
from pipeline.macro_signal_thresholds import Channel

logger = logging.getLogger(__name__)

PROMPT_PATH = config.MACRO_SIGNAL_PROMPT

_ALLOWED_CHANNELS = {c.value for c in Channel}
_ALLOWED_ASSETS = {
    "treasuries", "real_rates", "credit", "usd", "semis",
    "broad_equities", "duration_growth", "consumer", "housing",
}
_REQUIRED_FIELDS = ("channel", "entry_point", "assets", "transmission", "suspect", "suspect_reason")
_BANNED_TERMS = [
    "signals that", "suggests", "could mean", "investors fear", "markets are watching",
]
# CONFIRMED LIVE (2026-09-11, 2026-09-21 real events): a WEAK-tier event
# with several modest, mixed-direction member moves and no dramatic
# single number to describe sometimes gets a transmission that narrates
# the model's OWN classification process ("No series breached the HIGH
# threshold", "did not trigger a significant event") instead of
# describing what actually moved - a real violation of "it never
# classifies" (Appendix A) that _BANNED_TERMS didn't catch, since none
# of those exact phrases matched. This is commentary about the tier
# decision itself, not a mechanism description - the spec's own rule is
# that even a quiet WEAK event should still describe the real (if
# modest) move, never comment on the absence of a bigger one.
_TIER_COMMENTARY_TERMS = [
    "breached the high threshold", "breach the high threshold", "breached the threshold",
    "did not trigger", "does not trigger", "no series breached", "no high-tier",
    "not a significant event", "did not reach the high", "remained within",
    "within their typical range", "within its typical range", "did not clear",
]
_MAX_ENTRY_POINT_WORDS = 4
_MAX_TRANSMISSION_WORDS = 25


class InterpretationValidationError(ValueError):
    pass


def load_system_prompt() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Prompt file is empty: {PROMPT_PATH}")
    return text


def build_user_prompt(event: dict[str, Any]) -> str:
    """Serializes a collapsed event's facts into the user-turn prompt.
    `event` shape: {release_id, knowledge_time (ISO string), channel,
    members: [{series_id, value, move_bp, target_year, z_score, tier,
    classification_basis}], dfedtaru_ctx_bp?}
    """
    import json
    return json.dumps(event, indent=2, default=str)


def validate_interpretation(
    payload: dict[str, Any], *, expected_channel: str, members: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mirrors classifier.py's validate_classification() role: required
    keys present, enum membership, cross-field consistency, banned-language
    scan. Raises InterpretationValidationError on any violation - callers
    should skip the event, never fabricate a fallback sentence (there's no
    safe default the way WEAK is a safe default tier).

    members (real event.members dicts - series_id/value/move_bp/z_score/
    tier), when given, are cross-checked against `transmission`'s own bp
    figures and direction words (real frontend ticket item 7, 2026-09-25:
    "all numbers must be correct and consistent with each other" - the
    original "31bp for a 5bp move" T10Y2Y bug would have been caught
    here). Optional (defaults to no check) only so existing unit tests
    that construct a bare payload without a real event don't all need
    updating - every real call site in interpret_event/interpret_events_
    batch always passes it."""
    missing = [f for f in _REQUIRED_FIELDS if f not in payload]
    if missing:
        raise InterpretationValidationError(f"Missing required fields: {missing}")

    # channel is deterministic - it comes from the series-to-channel
    # mapping (macro_signal_thresholds.py), computed BEFORE this event
    # was ever sent to the model, not something the model infers. Asking
    # the model to echo it back is a confirmation/consistency check, not
    # the source of truth: CONFIRMED LIVE the model occasionally answers
    # "unclear" for this field even though it was given verbatim in the
    # input (channel is never actually ambiguous), and dropping the
    # whole event over a field that was never in question is a real
    # cost with no corresponding benefit. Log any mismatch (worth
    # watching for a model that starts reclassifying rather than
    # transcribing), then force the known-correct value - the model's
    # own answer for this one field is never authoritative.
    model_channel = payload.get("channel")
    if model_channel != expected_channel:
        logger.warning(
            "[MACRO_SIGNAL_INTERPRET] model returned channel=%r, expected %r (deterministic) - "
            "overriding to the known value, not treating as event-invalidating",
            model_channel, expected_channel,
        )
    payload["channel"] = expected_channel
    channel = expected_channel

    entry_point = payload["entry_point"]
    if not isinstance(entry_point, str) or not entry_point.strip():
        raise InterpretationValidationError("entry_point must be a non-empty string")
    if entry_point.lower() != "unattributed" and len(entry_point.split()) > _MAX_ENTRY_POINT_WORDS:
        raise InterpretationValidationError(
            f"entry_point exceeds {_MAX_ENTRY_POINT_WORDS} words: {entry_point!r}"
        )

    assets = payload["assets"]
    if not isinstance(assets, list) or not (1 <= len(assets) <= 3):
        raise InterpretationValidationError(f"assets must be a list of 1-3 items, got {assets!r}")
    bad_assets = [a for a in assets if a not in _ALLOWED_ASSETS]
    if bad_assets:
        raise InterpretationValidationError(f"assets contains disallowed values: {bad_assets}")

    transmission = payload["transmission"]
    if not isinstance(transmission, str) or not transmission.strip():
        raise InterpretationValidationError("transmission must be a non-empty string")
    if len(transmission.split()) > _MAX_TRANSMISSION_WORDS:
        raise InterpretationValidationError(
            f"transmission exceeds {_MAX_TRANSMISSION_WORDS} words ({len(transmission.split())}): {transmission!r}"
        )

    suspect = payload["suspect"]
    if not isinstance(suspect, bool):
        raise InterpretationValidationError(f"suspect must be a bool, got {suspect!r}")

    suspect_reason = payload["suspect_reason"]
    if suspect and (not isinstance(suspect_reason, str) or not suspect_reason.strip()):
        raise InterpretationValidationError("suspect_reason must be a non-empty string when suspect is true")
    if not suspect and suspect_reason is not None:
        raise InterpretationValidationError("suspect_reason must be null when suspect is false")

    scan_text = f"{entry_point} {transmission}".lower()
    hit_terms = [t for t in _BANNED_TERMS if t in scan_text]
    if hit_terms:
        raise InterpretationValidationError(f"Banned commentary language found: {hit_terms}")

    tier_commentary_hits = [t for t in _TIER_COMMENTARY_TERMS if t in scan_text]
    if tier_commentary_hits:
        raise InterpretationValidationError(
            f"transmission narrates the tier decision instead of describing the "
            f"move (violates 'it never classifies'): {tier_commentary_hits}"
        )

    if members is not None:
        fact_check = check_transmission_matches_real_numbers(transmission, members)
        if not fact_check.ok:
            raise InterpretationValidationError(
                f"transmission's numbers don't match the real event data: {fact_check.problems}"
            )

    return payload


_MAX_INTERPRET_ATTEMPTS = 2


def interpret_event(
    event: dict[str, Any],
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int | None = None,
    max_attempts: int | None = None,
) -> dict[str, Any] | None:
    """One call (up to max_attempts, default 2) to {base_url}/chat/
    completions via classify_with_model() (reused directly from
    pipeline/classifier.py - same urllib/extract_json_object/validator
    shape as every other LLM call in this service). Returns None (does
    not raise) once every attempt fails - logged, and the caller must
    skip this event rather than fabricate a fallback sentence (there is
    no safe default the way WEAK is a safe default tier).

    A single retry on validation failure (not just HTTP failure) is
    deliberate here, unlike Taiwan's GDELT relevance check
    (_classify_gdelt_relevance, single-attempt-only): that call has a
    safe fallback (WEAK) to drop to, so a bad response just means a
    slightly duller classification, cheap to accept. This call has NO
    safe fallback - a dropped event is a real HIGH/WEAK signal lost
    entirely, and CONFIRMED LIVE the model is not fully deterministic
    even at temperature=0 (e.g. a "channel" field mismatch or tier-
    commentary transmission on one attempt, absent on a retry with the
    identical prompt) - so the cost/value tradeoff favors one retry
    here, matching classify_article_with_fallback's own multi-attempt
    pattern in classifier.py rather than the single-shot Taiwan one.
    """
    model = model or config.MACRO_SIGNAL_MODEL
    api_key = api_key or config.OPENAI_API_KEY
    base_url = base_url or config.OPENAI_BASE_URL
    timeout = timeout or config.OPENAI_TIMEOUT
    max_attempts = max_attempts or _MAX_INTERPRET_ATTEMPTS

    system_prompt = load_system_prompt()
    user_prompt = build_user_prompt(event)
    expected_channel = event["channel"]

    def _validator(payload: dict[str, Any]) -> dict[str, Any]:
        return validate_interpretation(payload, expected_channel=expected_channel, members=event["members"])

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return classify_with_model(
                system_prompt, user_prompt, model, api_key, base_url, timeout,
                validator=_validator, max_tokens=400, stage="macro_signal_interpret",
            )
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "[MACRO_SIGNAL_INTERPRET] attempt %d/%d failed for release_id=%s "
                "knowledge_time=%s event=%s: %s",
                attempt, max_attempts, event.get("release_id"), event.get("knowledge_time"), event, exc,
            )

    # Include the full event (member series, values, z-scores) in the
    # final warning, not just the validator's field-level error -
    # CONFIRMED LIVE that a bare "channel 'unclear' not in {...}" message
    # alone was not enough to reproduce or diagnose a real failure after
    # the fact (a synthetic reconstruction of a similarly-shaped event
    # did not reproduce the same failure - the exact real input that
    # caused it was already lost).
    logger.warning(
        "[MACRO_SIGNAL_INTERPRET] giving up after %d attempts for release_id=%s "
        "knowledge_time=%s event=%s: %s",
        max_attempts, event.get("release_id"), event.get("knowledge_time"), event, last_exc,
    )
    return None


def interpret_events_batch(
    events: list[dict[str, Any]], *, model: str | None = None,
) -> list[dict[str, Any]]:
    """ThreadPoolExecutor(max_workers=config.MACRO_SIGNAL_CLASSIFY_CONCURRENCY)
    fan-out, one interpret_event call per event - same shape as
    classify_gdelt_articles's concurrency pattern. Events whose
    interpret_event call fails (returns None) are dropped from the
    result, not retried and not replaced with a fallback."""
    if not events:
        return []
    results: list[dict[str, Any] | None] = [None] * len(events)
    with ThreadPoolExecutor(max_workers=config.MACRO_SIGNAL_CLASSIFY_CONCURRENCY) as executor:
        futures = {
            executor.submit(interpret_event, event, model=model): i
            for i, event in enumerate(events)
        }
        for future in futures:
            i = futures[future]
            results[i] = future.result()
    return [
        {"event": event, "interpretation": result}
        for event, result in zip(events, results)
        if result is not None
    ]
