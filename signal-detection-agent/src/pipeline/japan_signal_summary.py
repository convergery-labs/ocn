"""Japan Signals spec Section 10.3 - the summary writer, the twice-daily
trader-facing digest layer sitting on top of everything
japan_signal_classifier.py has already classified.

Built as a plain function, not a new service - same scope decision
korea_signal_summary.py's own module docstring already made and explains
in full (no email, no scheduling, no new service; a follow-up decision
once real output has been seen, not assumed now). This module only
builds the summary TEXT via one LLM call, given already-classified rows
read from this same service's own DB (via models.jobs.list_all_results,
in controllers/run.py's generate_japan_signal_summary_for_date - this
module has no DB access itself, same pipeline/*.py layering boundary
every module in this service already follows).

Per spec's own explicit design intent ("Everything measurable is passed
in as a fact, never asked of the model"), no ranking formula is invented
here, same reasoning korea_signal_summary.py's own module docstring
gives for Korea's identical "rank" wording - Section 10.3 never defines
a rank formula anywhere in the document. Rows are pre-sorted by
signal_detection (signal before weak_signal) then recency, and the
model's own job is to write the sections faithfully from what it's
given.

Section 10.3's WATCHING section ("companies diverging from their own
pattern that have not announced anything") is populated from real
jp_watching rows - see japan_signal_classifier.py's own
classify_stale_revision_pattern for how those rows are computed (real
elapsed days since a company's last genuine revision vs. its own stored
cadence, gated to trusted habits only, never a prediction). If no real
jp_watching row exists in the window (nothing currently qualifies as
stale enough), the section is still omitted here (see
_build_watching_lines' own docstring) - the same "omit an empty section"
instruction the spec itself gives, now genuinely meaning "nothing
qualified" rather than "this service has no way to compute it".
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.request import Request, urlopen

import config

logger = logging.getLogger(__name__)

# Spec Section 10.3, verbatim instructions text - not paraphrased, same
# reasoning korea_signal_summary.py's own _SUMMARY_WRITER_SYSTEM_PROMPT
# gives for keeping 8.4's wording exact: the doc's own phrasing ("No
# adjectives. No hedging.") is calibrated language, not filler safe to
# reword.
_SUMMARY_WRITER_SYSTEM_PROMPT = """You are writing a twice-daily summary for a trader covering
Japanese semiconductor, equipment and materials companies.

Items arrive already classified. Each carries its rank, its age,
how many publications carried it, whether English coverage was
found, and the company's revision habit. All of these are
measured. Use them exactly as given. Never estimate a figure
that was not supplied.

Write the COMPANY LEVEL section only (two other sections,
INDUSTRY LEVEL and WATCHING, are already-finished text appended
separately before/after your own output - never write either of
those sections yourself, even if one seems implied):

COMPANY LEVEL
   Ranked items, one line each: company, code, what happened,
   age, and the companies it reads through to.
   For any forecast revision you MUST state the company's habit
   alongside the size of the revision. A small revision from a
   company that never revises is more important than a large one
   from a company that always does, and the line must make that
   clear.

Rules:
- Group items covering one story into one line, with the count.
- Mark unconfirmed press reports as unconfirmed.
- Report age as a fact. Never predict when English coverage
  will appear.
- No adjectives. No hedging.
- Omit an empty section. If nothing qualifies at all, say so in
  one line and stop.
- Every number in your output (age, days, percentages, ratios)
  must be copied character-for-character from the supplied field.
  Do not compute, round differently, or re-derive any number from
  a date or from another number - copy the given value as-is."""


def _age_hours(row: dict[str, Any]) -> float | None:
    """Hours between the row's own `published` and now (UTC) - same real
    computation korea_signal_summary.py's own _age_hours already does.
    Returns None for a J3 row (published is always null - see
    classify_missing_revision's own result shape, an absence has no real
    publication timestamp to compute an age from).
    """
    from datetime import datetime, timezone

    published = row.get("published")
    if not published:
        return None
    try:
        dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 1)


def _build_industry_line(industry_rows: list[dict[str, Any]]) -> str | None:
    """Section 1 (INDUSTRY LEVEL): the real SEAJ equipment-sales figure,
    only if classified as a real SIGNAL (spec's own "if it was classified
    as a Signal" condition - a WEAK/NOISE industry reading is not
    reported here at all, matching J4's own real classify_industry_
    equipment_sales rule that most months land WEAK/NOISE, not every
    month being noteworthy). Returns None (section omitted) if no real
    industry SIGNAL row exists in this window.

    Returns the LITERAL final section text (not a prompt fragment fed to
    the model - same reasoning as _build_watching_lines' own docstring):
    confirmed live 2026-09-30 gpt-4o-mini also unreliably restates this
    section when asked to write it itself - repeat calls on the exact
    same real data produced a fabricated wrong year ("October 2023" for a
    real October-2026 reading) and, separately, "Not specified"
    placeholders for fields that were genuinely present in the prompt.
    classify_industry_equipment_sales' own signal_reason is already a
    complete, real, spec-shaped sentence ("state the month, the reading,
    and how far it sits from its own average") - there is nothing left
    for the model to add here, so it is used as this section's text
    verbatim rather than re-summarized.
    """
    signal_rows = [r for r in industry_rows if r.get("signal_detection") == "signal"]
    if not signal_rows:
        return None
    # Newest first (list_all_results' own ORDER BY) - report the single
    # most recent real signal month, not every historical one that
    # happens to still be in the window.
    reason = signal_rows[0].get("signal_reason")
    return f"INDUSTRY LEVEL\n{reason}" if reason else None


def _build_company_lines(company_rows: list[dict[str, Any]]) -> list[str]:
    """Section 2 (COMPANY LEVEL): one line per real classified
    company-level row (J1/J2/J3/J5/J6/J7 - everything except J4's
    industry-wide reading, handled separately above). Deliberately
    verbose/labeled, not compact - same reasoning korea_signal_summary.py's
    own _build_item_lines gives: the model is told to use these "exactly
    as given", so an ambiguous encoding risks the model guessing at a
    field's meaning, which Section 10.3's own instructions say never to
    do.

    "the companies it reads through to" (spec's own required field): read
    from metadata.customers when present (added this session to
    JAPAN_TICKER_UNIVERSE - see japan_ticker_universe.py's own docstring;
    NOT yet wired into any classify_* function's own stored metadata, so
    this looks it up fresh from the ticker universe by code here, the
    same real customers list the artifact's own reference section reads -
    not fabricated, but see this module's own top docstring on why
    customers itself is still unverified against a primary source).
    """
    from pipeline.japan_ticker_universe import JAPAN_TICKER_UNIVERSE

    customers_by_code = {t["code"]: t.get("customers") or [] for t in JAPAN_TICKER_UNIVERSE}

    lines = []
    for row in company_rows:
        meta = row.get("metadata") or {}
        code = meta.get("code")
        company = meta.get("company") or code or "-"
        age = _age_hours(row)
        reads_through_to = customers_by_code.get(code, [])

        parts = [f"signal: {row.get('signal_detection')}"]
        parts.append(f"company: {company}")
        if code:
            parts.append(f"code: {code}")
        if row.get("signal_reason"):
            parts.append(f"what: {row['signal_reason']}")
        if age is not None:
            parts.append(f"age_hours: {age}")
        if reads_through_to:
            parts.append(f"reads_through_to: {', '.join(reads_through_to)}")

        # Spec's own explicit MUST for a forecast revision (J1): state the
        # habit alongside the size, so a small revision from a rarely-
        # revising company doesn't read as less important than a large
        # one from a company that always revises.
        if meta.get("source_category") == "jp_forecast" and "habit_typical_size_pct" in meta:
            habit_pct = meta.get("habit_typical_size_pct")
            revised_pct = meta.get("operating_profit_pct_change")
            if habit_pct is not None:
                parts.append(f"company_typical_revision_size_pct: {habit_pct}")
            if revised_pct is not None:
                parts.append(f"this_revision_pct: {revised_pct}")

        publications = meta.get("publications_carrying_this")
        if publications is not None:
            parts.append(f"publications_carrying_this: {publications}")

        unconfirmed = meta.get("unconfirmed")
        if unconfirmed:
            parts.append("unconfirmed: true")

        lines.append(" | ".join(parts))
    return lines


def _build_watching_lines(watching_rows: list[dict[str, Any]]) -> list[str]:
    """Section 3 (WATCHING): one rendered, final text line per real
    jp_watching row - a tracked company whose real elapsed time since its
    last genuine forecast revision now exceeds its own established
    cadence, computed by classify_stale_revision_pattern (see that
    function's own docstring for the full design and why it only ever
    produces weak_signal, never signal).

    Unlike _build_industry_line/_build_company_lines, this is NOT a
    prompt fragment fed to the model - it is the literal, final section
    text, assembled here in code and appended to the model's own output
    untouched (see generate_japan_signal_summary below). Confirmed live
    2026-09-30: gpt-4o-mini (SIGNAL_DETECTION_MODEL_V2/OPENAI_MODEL_V2 -
    this module's model at the time this was found; the summary writer
    was subsequently switched to config.JAPAN_SIGNAL_MODEL, a stronger
    tier, same day - see that constant's own comment in config.py)
    reliably FABRICATED the day-count numbers when asked to restate them
    itself (e.g. wrote "601 days" for Tokyo Electron when the real stored
    value is 783, on repeat calls, each producing a different wrong
    number, at temperature 0, even after the system prompt was tightened
    to explicitly demand verbatim copying) - a real, reproducible
    small-model weakness with multi-digit literal-copy tasks, not a data
    or formatting bug on this module's side (the correct real numbers
    were confirmed present in the actual prompt text sent). WATCHING
    items are pure arithmetic with no narrative judgment call to make
    (unlike COMPANY LEVEL's real synthesis job - "what happened" in
    prose, habit context, read-through), so nothing is lost by never
    letting the model touch these numbers at all - kept rendered in code
    even after the stronger model was adopted, as defense in depth: a
    section with zero narrative content has nothing to gain from an LLM
    call regardless of which model is configured.

    Returns an empty list (section omitted, matching the spec's own
    "omit an empty section" instruction, applied here in code instead of
    relying on the model to notice an empty input) when no real
    jp_watching row exists in this window.
    """
    lines = []
    for row in watching_rows:
        meta = row.get("metadata") or {}
        company = meta.get("company") or meta.get("code") or "-"
        code = meta.get("code")
        days_since = meta.get("days_since_last_revision")
        typical_gap = meta.get("typical_days_between_revisions")
        habit = meta.get("company_revision_habit")

        label = f"{company} ({code})" if code else company
        gap_clause = f"last filed a forecast revision {days_since} days ago" if days_since is not None else "has not filed a forecast revision in longer than usual"
        habit_clause = ""
        if typical_gap is not None and habit:
            habit_clause = f"; typically revises about every {typical_gap} days ({habit})"
        elif habit:
            habit_clause = f"; {habit}"
        lines.append(f"{label} {gap_clause}{habit_clause}.")
    return lines


def generate_japan_signal_summary(
    rows: list[dict[str, Any]],
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int | None = None,
) -> str:
    """Spec Section 10.3: one LLM call producing the twice-daily trader
    summary text, given already-classified japan_market_signal rows
    (caller reads these from agent_classifications - see
    controllers/run.py's generate_japan_signal_summary_for_date for the
    DB-reading side; this function is pure - no DB access, mirrors
    korea_signal_summary.py's own generate_korea_signal_summary boundary
    exactly).

    ``rows``: agent_classifications row dicts (as list_all_results
    already shapes them). Caller decides the window and pre-filters to
    source_type='japan_market_signal' - this function does not filter by
    source_type itself, same trust-the-caller convention
    generate_korea_signal_summary already follows.

    Rows are split three ways: industry (metadata.source_category ==
    'jp_industry'), watching (metadata.source_category == 'jp_watching' -
    see classify_stale_revision_pattern), and everything else
    (company-level) - each pre-sorted signal-before-weak_signal then
    newest-first by the caller - no fabricated numeric rank (see module
    docstring for why).

    INDUSTRY LEVEL and WATCHING are both deliberately NEVER sent to the
    model - see _build_industry_line's and _build_watching_lines' own
    docstrings for the real, confirmed-live reason (gpt-4o-mini reliably
    fabricates numbers, wrong years, and "not specified" placeholders
    when asked to restate already-final data). Both sections are rendered
    directly in code and stitched together with whatever the model
    produces for COMPANY LEVEL - the only section that genuinely needs
    narrative synthesis (grouping multi-source items into one line,
    stating a revision's size against the company's own habit in prose).
    The model is never shown INDUSTRY LEVEL/WATCHING's numbers at all, so
    it cannot alter them.
    """
    model = model or config.JAPAN_SIGNAL_MODEL
    api_key = api_key or config.OPENAI_API_KEY
    base_url = base_url or config.OPENAI_BASE_URL
    timeout = timeout or config.OPENAI_TIMEOUT

    if not rows:
        # Spec's own instruction: "If nothing qualifies at all, say so in
        # one line and stop." - true with zero rows before ever calling
        # the model, so no LLM call is spent restating what's already known.
        return "No qualifying Japan Signals items today."

    industry_rows = [r for r in rows if (r.get("metadata") or {}).get("source_category") == "jp_industry"]
    watching_rows = [r for r in rows if (r.get("metadata") or {}).get("source_category") == "jp_watching"]
    company_rows = [
        r for r in rows
        if (r.get("metadata") or {}).get("source_category") not in ("jp_industry", "jp_watching")
    ]

    industry_section = _build_industry_line(industry_rows) or ""
    company_lines = _build_company_lines(company_rows)
    watching_lines = _build_watching_lines(watching_rows)
    watching_section = ("WATCHING\n" + "\n".join(watching_lines)) if watching_lines else ""

    company_section = ""
    if company_lines:
        user_prompt = "COMPANY ITEMS (already classified, use exactly as given):\n" + "\n".join(company_lines)
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SUMMARY_WRITER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
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
            company_section = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
        except Exception as exc:
            logger.warning("[JAPAN_SIGNAL_SUMMARY] generation failed: %s", exc)
            company_section = ""

    sections = [s for s in (industry_section, company_section, watching_section) if s]
    if not sections:
        return "No qualifying Japan Signals items today."
    return "\n\n".join(sections)
