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
   Where a direction field is supplied, the line MUST open with
   that word - RAISED or CUT - before any number. Never write
   "changed by" or leave the direction to be inferred from a sign.
   Where operating_profit is supplied, state both figures as
   given (for example: 90bn -> 138bn), not the percentage alone.
   For any forecast revision you MUST state the company's habit
   alongside the size of the revision. A small revision from a
   company that never revises is more important than a large one
   from a company that always does, and the line must make that
   clear.

Rules:
- Group items covering one story into one line, with the count.
- Where same_day_filings is supplied, the company released that many
  disclosures on one day. Report it as one item and state the count -
  never as separate entries.
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


def _format_age(hours: float | None) -> str | None:
    """Render an age the way a reader states it out loud: "4h ago",
    "3d ago", "2mo ago". A raw hour count past a day or so ("1520.6
    hours") forces the reader to divide before they can judge whether an
    item is fresh, which is the one thing this field exists to answer.
    """
    if hours is None:
        return None
    if hours < 1:
        return "just now"
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24.0
    if days < 30:
        return f"{int(days)}d ago"
    months = days / 30.0
    if months < 12:
        return f"{int(months)}mo ago"
    return f"{days / 365.0:.1f}y ago"


def _format_pct(value: float | None, signed: bool = False) -> str | None:
    """Render a percentage as the stored figure states it, dropping a
    trailing zero decimal: 53.3% stays 53.3%, 27.6% stays 27.6%, 40.0%
    reads 40%. ``signed`` prefixes a + on a positive value, for a field
    where the direction is part of the number.
    """
    if value is None:
        return None
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    if signed and value > 0:
        text = f"+{text}"
    return f"{text}%"


def _format_jpy_millions(value: float | None) -> str | None:
    """Render a JPY-millions figure (the unit every irbank_financials
    table stores) at the scale a reader uses: ¥138bn, ¥34.5bn, ¥1.4tn.

    Keeps a decimal place where the real figure has one, so a stored
    34500 reads as ¥34.5bn rather than being rounded to ¥34bn - these
    are the filing's own reported figures, and a reader comparing them
    against the filing should see the same number it states.
    """
    if value is None:
        return None
    millions = abs(float(value))
    sign = "-" if value < 0 else ""
    if millions >= 1_000_000:
        scaled, unit = millions / 1_000_000, "tn"
    elif millions >= 1_000:
        scaled, unit = millions / 1_000, "bn"
    else:
        scaled, unit = millions, "m"
    # Drop the decimal only when it is genuinely zero.
    text = f"{scaled:.1f}".rstrip("0").rstrip(".")
    return f"{sign}¥{text}{unit}"


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


_SIGNAL_LABEL = {"signal": "SIGNAL", "weak_signal": "WEAK", "noise": "NOISE"}

# How far behind or ahead of schedule a company must be before the
# reading means anything. A quarter does not land exactly on its share
# of the year - results cluster around filing dates and seasonal demand
# - so a few points either side of the elapsed year is ordinary. 5
# points is the width of that ordinary band: inside it the company is
# on track, outside it the gap is the story.
_PROGRESS_ON_TRACK_BAND_PTS = 5.0


def signal_implication(meta: dict[str, Any]) -> str:
    """Return Positive / Negative / Mixed / Unclear for one classified row.

    Sets the colour of the headline number on a trading screen, so a
    direction is only claimed where the filing's own figures establish
    one. Each branch compares two real stored values; nothing is
    inferred from the kind of event, because a buyback or a capacity
    investment carries no stated direction however it is conventionally
    read.
    """
    # A yen-denominated forecast revision: the sign of the change is the
    # direction the company moved its own guidance.
    pct = meta.get("operating_profit_pct_change")
    if pct is not None:
        if pct > 0:
            return "Positive"
        if pct < 0:
            return "Negative"
        return "Mixed"

    # Margin-percentage guidance (see _MARGIN_BASED_CODES in the
    # classifier): there is no previous forecast to measure against, but
    # the filing states the same period's prior-year actual, which is the
    # comparison the company itself presents.
    revised = meta.get("margin_revised_pct")
    reference = meta.get("margin_reference_prior_year_actual_pct")
    if revised is not None and reference is not None:
        if revised > reference:
            return "Positive"
        if revised < reference:
            return "Negative"
        return "Mixed"

    # Results against forecast: progress toward the full-year target
    # against how much of the year has actually gone.
    progress = meta.get("progress_pct")
    elapsed = meta.get("fiscal_year_elapsed_pct")
    if progress is not None and elapsed is not None:
        gap = progress - elapsed
        if gap > _PROGRESS_ON_TRACK_BAND_PTS:
            return "Positive"
        if gap < -_PROGRESS_ON_TRACK_BAND_PTS:
            return "Negative"
        return "Mixed"

    # The national equipment reading: its own year-on-year sign.
    yoy = meta.get("yoy_pct")
    if yoy is not None:
        if yoy > 0:
            return "Positive"
        if yoy < 0:
            return "Negative"
        return "Mixed"

    # Ownership, buyback, capacity, press and a missing announcement
    # state no direction of their own. A holder crossing 5% may be
    # accumulating or unwinding; a buyback may signal confidence or
    # absent opportunity. Claiming a colour here would assert something
    # the filing does not.
    return "Unclear"


def _why_unusual(meta: dict[str, Any], row: dict[str, Any]) -> list[str]:
    """The WHY IT'S UNUSUAL lines: what makes this item stand out from
    the company's own record, stated only from measured fields.

    Every line is a stored value or a ratio between two of them. The
    company's own stated reason is quoted only where the filing supplies
    one, never summarized.
    """
    lines: list[str] = []
    pct = meta.get("operating_profit_pct_change")
    typical = meta.get("habit_typical_size_pct")
    if pct is not None and typical:
        multiple = abs(pct) / typical
        if multiple >= 1.2:
            word = "raise" if pct > 0 else "cut"
            lines.append(
                f"{_format_multiple(multiple)} its usual {word} "
                f"({_format_pct(typical)} typical)."
            )
    sample = meta.get("habit_sample_size")
    if pct is not None and sample:
        lines.append(f"Measured against {sample} revision{'s' if sample != 1 else ''} on record.")
    if not lines:
        # Every other signal type carries its own finished sentence.
        reason = row.get("signal_reason")
        if reason:
            lines.append(reason)
    return lines


def _format_multiple(m: float) -> str:
    """Render a ratio the way it is spoken: "Nearly 2x", "Over 3x"."""
    nearest = round(m)
    if nearest >= 2 and abs(m - nearest) <= 0.15:
        return f"{'Nearly ' if m < nearest else 'Just over '}{nearest}x"
    if m >= 2:
        return f"Over {int(m)}x"
    return f"{m:.1f}x".replace(".0x", "x")


def build_signal_block(row: dict[str, Any]) -> str:
    """Render one classified row as the trader-facing block.

    Built entirely in Python rather than by the model: every field here
    is already a measured value, and a model asked to restate final
    figures was confirmed to alter them. Sections with no data are
    omitted rather than filled, the same rule the spec gives for the
    summary's own empty sections.
    """
    meta = row.get("metadata") or {}
    code = meta.get("code") or ""
    tier = _SIGNAL_LABEL.get(row.get("signal_detection"), "")
    # J4 reads the national equipment market and has no company of its
    # own. Naming the series rather than the subject keeps a run of
    # monthly readings legible as one recurring release: the same label
    # on every row with only the period changing reads as a category
    # repeated, not a series continuing.
    subject = meta.get("company") or code or "SEAJ equipment billings"
    qualifier = code or meta.get("period") or ""

    out = [f"{tier}   {subject} {qualifier}".rstrip()]

    pct = meta.get("operating_profit_pct_change")
    if pct is not None:
        headline = f"{'RAISED' if pct > 0 else 'CUT'} full-year op profit {_format_pct(pct, signed=True)}"
        prev = _format_jpy_millions(meta.get("operating_profit_previous"))
        rev = _format_jpy_millions(meta.get("operating_profit_revised"))
        if prev and rev:
            headline += f"  {prev} → {rev}"
        out.append(f"         {headline}")

    why = _why_unusual(meta, row)
    if why:
        out.append("")
        out.append("WHY IT'S UNUSUAL")
        out.extend(f"         {line}" for line in why)

    # Imported here rather than at module scope: japan_signal_view
    # imports this module for its own formatting helpers, so a top-level
    # import of the read-through tables would close that loop.
    from pipeline.japan_earnings_calendar import next_report_for
    from pipeline.japan_read_through import links_for

    links = links_for(meta.get("code"))
    if links:
        out.append("")
        out.append("WHAT TO DO WITH IT")
        shown = links[:3]
        out.append("         → " + ", ".join(link["name"] for link in shown))
        lead = shown[0]
        kind = {
            "Competitor": "Direct peer",
            "Shared demand": "Peers, same end demand",
            "Customer": "Buys from them",
            "Supplier": "Sells to them",
        }.get(lead["relationship"], lead["relationship"])
        out.append(f"           {kind}. {lead['strength'].capitalize()} read, "
                   f"{lead['lag']}.")

        report = next_report_for(lead["ticker"])
        if report:
            iso, event = report
            out.append("")
            out.append("WHEN YOU'LL KNOW")
            out.append(f"         {event} on {iso}.")

    footer = []
    age = _format_age(_age_hours(row))
    if age:
        footer.append(f"Filed {age}")
    if meta.get("unconfirmed"):
        footer.append("unconfirmed")
    if footer:
        out.append("")
        out.append("         " + " · ".join(footer))
    return "\n".join(out)


def _group_same_day(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse rows for one company on one day into a single entry.

    A company filing several disclosures on the same day is one story to
    a reader, not several - a results filing and a buyback announcement
    released together describe one decision. Reporting them as separate
    entries makes one event look like a cluster of activity, which is
    the opposite of what a summary is for.

    Grouping is by (code, calendar day of `published`), which is a real
    editorial boundary rather than a tunable window: filings released on
    the same day were released together. The strongest classification in
    a group leads, its own reason carries the entry, and the others are
    counted alongside it. A row with no code or no date cannot be grouped
    and passes through untouched.
    """
    rank = {"signal": 0, "weak_signal": 1, "noise": 2}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    out: list[dict[str, Any]] = []
    for row in rows:
        meta = row.get("metadata") or {}
        code = meta.get("code")
        day = str(row.get("published") or "")[:10]
        if not code or not day:
            out.append(row)
            continue
        groups.setdefault((code, day), []).append(row)

    for members in groups.values():
        if len(members) == 1:
            out.append(members[0])
            continue
        members.sort(key=lambda r: rank.get(r.get("signal_detection"), 3))
        lead = dict(members[0])
        lead["_grouped_count"] = len(members)
        lead["_grouped_categories"] = sorted({
            (m.get("metadata") or {}).get("source_category")
            for m in members
            if (m.get("metadata") or {}).get("source_category")
        })
        out.append(lead)

    out.sort(key=lambda r: (rank.get(r.get("signal_detection"), 3),
                            str(r.get("published") or "")), reverse=False)
    return out


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

    company_rows = _group_same_day(company_rows)

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

        # Direction leads, as a bare verb the model is told to open with.
        # "RAISED"/"CUT" answers the reader's first question before any
        # number does; a percentage alone leaves the direction to be
        # inferred from a sign or from prose further along the line.
        pct_change = meta.get("operating_profit_pct_change")
        if pct_change is not None:
            parts.append(f"direction: {'RAISED' if pct_change > 0 else 'CUT'}")

        if row.get("signal_reason"):
            parts.append(f"what: {row['signal_reason']}")
        age_text = _format_age(age)
        if age_text:
            parts.append(f"age: {age_text}")
        if reads_through_to:
            parts.append(f"reads_through_to: {', '.join(reads_through_to)}")

        # Spec's own explicit MUST for a forecast revision (J1): state the
        # habit alongside the size, so a small revision from a rarely-
        # revising company doesn't read as less important than a large
        # one from a company that always revises.
        if meta.get("source_category") == "jp_forecast" and "habit_typical_size_pct" in meta:
            habit_pct = meta.get("habit_typical_size_pct")
            if habit_pct is not None:
                parts.append(f"company_typical_revision_size_pct: {_format_pct(habit_pct)}")
            if pct_change is not None:
                parts.append(f"this_revision_pct: {_format_pct(pct_change, signed=True)}")

            # The absolute figures behind the percentage. A reader judging
            # materiality needs the yen amounts, not just the ratio between
            # them - both are already stored by classify_forecast_revision.
            previous = _format_jpy_millions(meta.get("operating_profit_previous"))
            revised = _format_jpy_millions(meta.get("operating_profit_revised"))
            if previous and revised:
                parts.append(f"operating_profit: {previous} -> {revised}")

        grouped = row.get("_grouped_count")
        if grouped:
            parts.append(f"same_day_filings: {grouped}")
            cats = row.get("_grouped_categories") or []
            if cats:
                parts.append(f"same_day_categories: {', '.join(cats)}")

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
