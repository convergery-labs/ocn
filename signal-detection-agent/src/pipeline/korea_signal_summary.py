"""Korea Signals spec Section 8.4 - the summary writer, the twice-daily
trader-facing digest layer sitting on top of everything
korea_signal_classifier.py has already classified.

Scope note (2026-09-23): built as a plain function, not a new service.
The existing precedent for a digest layer (signal-herald) is a full
separate FastAPI service - its own port, SMTP dispatch, A2A protocol -
built specifically for the much larger ai_news/AI-universe taxonomy.
Building an equivalent for Korea Signals was judged out of scope for now;
this module only builds the summary TEXT via one LLM call, given
already-classified rows read from this same service's own DB (via
models.jobs.list_all_results, in controllers/run.py's
generate_korea_signal_summary - this module has no DB access itself, same
pipeline/controllers layering every other pipeline/*.py module in this
service already follows). No email, no scheduling, no new service - those
are a real follow-up decision once real output has been seen against real
classified data, not assumed now.

Per spec's own explicit design intent ("Everything the system can work
out for itself is passed in as a fact, never asked of the model"), no
ranking formula is invented here - the spec's own Step 8 ("rank the
results") and Section 8.4 ("each one carries its own rank") never define
a rank formula anywhere in the document, unlike Section 5's explicit
numeric thresholds. Rather than fabricate an unspecified formula, items
are passed to the model pre-sorted by signal_detection (signal before
weak_signal) then recency, and the model's own job (per 8.4's actual
instructions) is to write the two sections faithfully from what it's
given - not to invent a number that was never supplied, which is exactly
the failure mode 8.4's own instructions warn against.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.request import Request, urlopen

import config

logger = logging.getLogger(__name__)

# Spec Section 8.4, verbatim instructions text - not paraphrased, for the
# same reason _QUALIFICATION_NEWS_SYSTEM_PROMPT in korea_signal_classifier.py
# keeps 8.1's wording exact: the doc's own phrasing ("No adjectives. No
# hedging. State it or leave it out.") is calibrated language, not filler
# that's safe to reword.
_SUMMARY_WRITER_SYSTEM_PROMPT = """You are writing a twice-daily summary for a trader covering
Korean semiconductor and electronics companies.

You receive items that have already been classified. Each one
carries its own rank, how many publications carried it, how old
it is, and whether English coverage was found. All of these are
measured. Use them exactly as given. Never estimate a figure
that was not supplied to you.

Write two sections, in this order:

1. MARKET LEVEL
   The export figure, if one was classified as a Signal. State
   the period, the reading, and how far it sits from its own
   recent average. This is a national figure - do not attribute
   it to any company.

2. COMPANY LEVEL
   Ranked items. One line each: company, code, what happened,
   how old it is, and the companies it reads through to.

Rules:
- Group items covering the same story into one line and say how
  many publications carried it.
- Report the age of an item as a fact. Never predict when
  English coverage will appear.
- If English coverage was already found, say so plainly.
- Report a rumour demand and its answer as one item, and state
  how long the company took to reply.
- No adjectives. No hedging. State it or leave it out.
- If nothing qualifies, say so in one line and stop. Do not pad
  the summary."""

# source_category values that legitimately have NO metadata.ticker at all
# (S1 would be the export-figure market-level item once implemented - not
# yet, see korea_signal_classifier.py's own module docstring) - excluded
# from "company reads through to" lookups rather than crashing on a
# missing field.
_MARKET_LEVEL_CATEGORIES = frozenset({"export_surprise"})


def _age_hours(row: dict[str, Any]) -> float | None:
    """Hours between the row's own `published` and now (UTC) - the "how
    old it is" fact 8.4 requires be reported, never predicted or omitted
    once known.
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


def _build_item_lines(rows: list[dict[str, Any]]) -> list[str]:
    """Render each classified row into the plain-text, measured-facts-only
    line format the model is given - one line per row, not prose, so the
    model receives exactly the same discrete facts 8.4's own instructions
    describe ("rank", "publications carried", "how old", "English
    coverage") rather than a paragraph it would need to parse back apart.

    Deliberately verbose/labeled (not a compact CSV-like row) - the model
    is explicitly told to use these "exactly as given", so an ambiguous or
    truncated encoding risks the model guessing at a field's meaning,
    which is the one thing 8.4 says never to do.
    """
    lines = []
    for row in rows:
        meta = row.get("metadata") or {}
        ticker = meta.get("ticker") or meta.get("stock_code") or "-"
        raw_title = row.get("title") or ""
        title = meta.get("translated_title") or raw_title
        age = _age_hours(row)
        publications = meta.get("publications_carrying_this")
        english_found = meta.get("english_coverage_found")
        english_delta = meta.get("english_coverage_hours_after_korean")

        # DART filing titles are consistently stored as "Company Name
        # (stock_code): report_nm" (confirmed live against real stored
        # rows, e.g. "SK Hynix (000660): 현금ㆍ현물배당결정") - the company
        # name is embedded in the raw title, not its own metadata field.
        # Only attempted for DART-sourced categories (everything except
        # qualification_news) - S7's title is a real, unmodified headline
        # that can itself legitimately contain a colon (confirmed live:
        # real RSS headlines like "[TGS 플레이노트] ... : ..." exist in
        # this same data), which would make this same split silently
        # mis-parse a headline fragment as a company name. S7 rows fall
        # back to the ticker alone instead - a real, deliberate omission,
        # not an oversight.
        source_category = meta.get("source_category")
        company = None
        if source_category and source_category != "qualification_news":
            company_match = raw_title.split(":", 1)
            if len(company_match) > 1:
                company = company_match[0].split("(")[0].strip()

        parts = [f"signal: {row.get('signal_detection')}"]
        if company:
            parts.append(f"company: {company}")
        parts.append(f"ticker: {ticker}")
        parts.append(f"what: {title}")
        if age is not None:
            parts.append(f"age_hours: {age}")
        if publications is not None:
            parts.append(f"publications_carrying_this: {publications}")
        if english_found is not None:
            parts.append(f"english_coverage_found: {english_found}")
        if english_delta is not None:
            parts.append(f"english_coverage_hours_after_korean: {english_delta}")
        if row.get("signal_reason"):
            parts.append(f"reason: {row['signal_reason']}")
        lines.append(" | ".join(parts))
    return lines


def generate_korea_signal_summary(
    rows: list[dict[str, Any]],
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: int | None = None,
) -> str:
    """Spec Section 8.4: one LLM call producing the twice-daily trader
    summary text, given already-classified korea_market_signal rows
    (caller reads these from agent_classifications - see
    controllers/run.py's generate_korea_signal_summary for the DB-reading
    side; this function is pure - no DB access, mirrors every other
    pipeline/*.py module's own no-DB-access boundary).

    ``rows``: agent_classifications row dicts (as list_all_results/
    list_results already shape them - signal_detection, signal_reason,
    metadata, published, title). Caller decides the window (today's rows,
    typically) and pre-filters to source_type='korea_market_signal' -
    this function does not filter by source_type itself, trusting the
    caller the same way classify_korea_signal_batch trusts its own
    caller's article pooling.

    Rows are pre-sorted signal-before-weak_signal, then newest-first - no
    fabricated numeric rank (see module docstring for why). NOISE rows are
    never expected here (classify_korea_signal_batch's own functions never
    insert a NOISE row - see korea_signal_classifier.py's own "NOISE:
    removed... not returned as a classified result at all" note on S7),
    so this function does not filter signal_detection itself either -
    whatever the caller passes in is what gets summarized.

    Known gap: "company" and "the companies it reads through to" (spec's
    own required per-item fields) are NOT populated - metadata carries
    ticker/stock_code (a company IDENTIFIER) but never the company's own
    name, and no korea_market_signal row anywhere stores which US-listed
    companies a Korean signal "reads through to" (KOREA_TICKER_UNIVERSE's
    own "what it tells you about" column - see the spec's Section 3 - is
    not wired into any classify_* function's stored metadata today). The
    model is left to work with ticker + translated headline text alone
    for company identification, and Rows never claim the read-through
    relationship the spec's own worked example shows (Section 6.5:
    "-> Nvidia, Micron Technology, Super Micro Computer") - a real,
    documented gap, not filled with an invented mapping here.
    """
    model = model or config.OPENAI_MODEL_V2
    api_key = api_key or config.OPENAI_API_KEY
    base_url = base_url or config.OPENAI_BASE_URL
    timeout = timeout or config.OPENAI_TIMEOUT

    if not rows:
        # Spec's own instruction: "If nothing qualifies, say so in one
        # line and stop." - true with zero rows before ever calling the
        # model, so no LLM call is spent restating what's already known.
        return "No qualifying Korea Signals items today."

    item_lines = _build_item_lines(rows)
    user_prompt = "ITEMS (already classified, use exactly as given):\n" + "\n".join(item_lines)

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
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return (content or "").strip()
    except Exception as exc:
        logger.warning("[KOREA_SIGNAL_SUMMARY] generation failed: %s", exc)
        return ""
