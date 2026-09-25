"""Post-INTERPRET numeric fact-check (spec follow-up, real frontend
ticket item 7, 2026-09-25): "All numbers must be correct and consistent
with each other." The original "31bp for a 5bp move" bug (T10Y2Y) would
have been caught by this - the LLM was free to write any bp figure in
`transmission`, and nothing checked it against the real move_bp before
the row was stored.

Scope: this checks what is mechanically checkable from a free-text
sentence without NLP - every bp number written in `transmission` must
appear (within rounding tolerance) among the real move_bp values for
this event's members, and the direction word found NEAR that specific
number (not the sentence as a whole) must agree with that number's own
real sign - checked per-number, not per-event, so a multi-member
sentence citing several different series' moves gets each one checked
independently (CONFIRMED LIVE, 2026-09-25: an earlier version of this
check only validated direction for single-member events and missed a
real wrong-direction-word bug on a multi-member sentence). It does NOT
check % level references, since a native-unit level appears in free
text in too many forms (e.g. "6.95%" vs "rose to 6.95") to match
reliably without false positives - flagged as a known gap below, not
silently ignored.

Does not check cross-event aggregate counts (HIGH/WEAK/NOISE/suppressed
totals matching /results) - that is a property of the whole run's output,
not of one event, and belongs in a separate post-run check, not here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FactCheckResult:
    ok: bool
    problems: list[str] = field(default_factory=list)


# Matches "31bp", "31 bp", "31bps", "+31bp", "-31bp" - the exact shape
# _MAX_TRANSMISSION_WORDS-constrained model output has actually produced
# live (see macro_signal_interpret.py's own _BANNED_TERMS neighbourhood).
_BP_NUMBER_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*bps?\b", re.IGNORECASE)

_RISE_WORDS = ("rose", "rising", "rise", "widened", "widening", "steepened", "steepening", "increased", "increasing", "up")
_FALL_WORDS = ("fell", "falling", "fall", "narrowed", "narrowing", "flattened", "flattening", "decreased", "decreasing", "down", "dropped")

# How close a written bp figure must be to a real move_bp to count as a
# match - not exact equality, since the model may write "50bp" for a
# real 49.99 (truncated, not rounded, per macro_signal_suppress.py's own
# choice) or round a multi-decimal value for readability.
_BP_MATCH_TOLERANCE = 1.0


# How many characters of context around a matched bp number to scan for
# a direction word - real examples confirmed live (2026-09-25, job 267):
# "steepening the 2s10s curve by 8bp" (word BEFORE the number, ~25 chars
# away) and "narrowing the 2s10s curve by 5bp" (same shape) - a window
# needs to comfortably cover "verb + object phrase + by" before the
# number, and a small amount after it too (e.g. "8bp steepening").
_DIRECTION_CONTEXT_CHARS = 40


def check_transmission_matches_real_numbers(
    transmission: str, members: list[dict[str, Any]],
) -> FactCheckResult:
    """members: the event's real per-series facts (the same dicts built
    in controllers.run's interpret_payloads - series_id/value/move_bp/
    z_score/tier). Checks every bp figure written in `transmission`
    against the real move_bp values, and that any direction word found
    NEAR that specific number in the text agrees with that number's own
    real sign.

    CONFIRMED LIVE (real frontend follow-up, 2026-09-25, job 267): the
    original version of this check only validated direction for
    single-member events, on the reasoning that a multi-member sentence
    might legitimately describe only one member's direction and an
    event-wide check would false-positive. That reasoning missed the
    real bug: a multi-member sentence can and does get the SIGN wrong
    for the number it's citing (e.g. "steepening the 2s10s curve by
    8bp" when T10Y2Y's real move was -8bp, a flattening) - the written
    NUMBER was correct (matched a real move_bp), only the WORD attached
    to it was wrong. Fixed by checking direction per-NUMBER instead of
    per-event: for each bp figure found in the text, locate the real
    member it matches, then scan a small window of text around that
    specific number (not the whole sentence) for a direction word and
    check it against THAT member's sign - so a correctly-described
    member elsewhere in the sentence never masks a wrong word next to a
    different member's number.
    """
    problems: list[str] = []
    real_move_bps = [m["move_bp"] for m in members if m.get("move_bp") is not None]

    for match in _BP_NUMBER_RE.finditer(transmission):
        written = float(match.group(1))
        real_match = next(
            (real for real in real_move_bps if abs(abs(written) - abs(real)) <= _BP_MATCH_TOLERANCE),
            None,
        )
        if real_match is None:
            problems.append(
                f"transmission cites {written}bp, but no member's real move_bp is within "
                f"{_BP_MATCH_TOLERANCE}bp of it (real values: {real_move_bps})"
            )
            continue
        if real_match == 0:
            continue  # no direction to check against a flat move

        window_start = max(0, match.start() - _DIRECTION_CONTEXT_CHARS)
        window_end = min(len(transmission), match.end() + _DIRECTION_CONTEXT_CHARS)
        nearby = transmission[window_start:window_end].lower()
        said_rise = any(w in nearby for w in _RISE_WORDS)
        said_fall = any(w in nearby for w in _FALL_WORDS)
        if said_rise and said_fall:
            continue  # ambiguous wording nearby (e.g. two direction words in the window) - not this check's job to parse
        if said_rise and real_match < 0:
            problems.append(
                f"transmission uses a rise/widen/steepen word near {written}bp, but the matching "
                f"member's real move_bp is negative ({real_match}) - a fall/narrow/flatten"
            )
        elif said_fall and real_match > 0:
            problems.append(
                f"transmission uses a fall/narrow/flatten word near {written}bp, but the matching "
                f"member's real move_bp is positive ({real_match}) - a rise/widen/steepen"
            )

    return FactCheckResult(ok=not problems, problems=problems)
