"""Post-INTERPRET numeric fact-check (spec follow-up, real frontend
ticket item 7, 2026-09-25): "All numbers must be correct and consistent
with each other." The original "31bp for a 5bp move" bug (T10Y2Y) would
have been caught by this - the LLM was free to write any bp figure in
`transmission`, and nothing checked it against the real move_bp before
the row was stored.

Scope: this checks what is mechanically checkable from a free-text
sentence without NLP - every bp number written in `transmission` must
appear (within rounding tolerance) among the real move_bp values for
this event's members, and the sentence's direction words (rose/widened/
steepened vs. fell/narrowed/flattened) must agree with those values'
sign. It does NOT check % level references, since a native-unit level
appears in free text in too many forms (e.g. "6.95%" vs "rose to 6.95")
to match reliably without false positives - flagged as a known gap
below, not silently ignored.

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


def check_transmission_matches_real_numbers(
    transmission: str, members: list[dict[str, Any]],
) -> FactCheckResult:
    """members: the event's real per-series facts (the same dicts built
    in controllers.run's interpret_payloads - series_id/value/move_bp/
    z_score/tier). Checks every bp figure written in `transmission`
    against the real move_bp values, and (if exactly one real move_bp is
    signed and non-zero) that the sentence's direction word agrees with
    its sign - loosely, not to reject a legitimately mixed-direction
    multi-series sentence which the interpret prompt explicitly allows
    ("pick the member closest to its own floor").
    """
    problems: list[str] = []
    real_move_bps = [m["move_bp"] for m in members if m.get("move_bp") is not None]

    written_numbers = [float(n) for n in _BP_NUMBER_RE.findall(transmission)]
    for written in written_numbers:
        if not any(abs(abs(written) - abs(real)) <= _BP_MATCH_TOLERANCE for real in real_move_bps):
            problems.append(
                f"transmission cites {written}bp, but no member's real move_bp is within "
                f"{_BP_MATCH_TOLERANCE}bp of it (real values: {real_move_bps})"
            )

    # Direction check only when the event is unambiguous: exactly one
    # real, non-zero move_bp, and the sentence uses a genuine direction
    # word - deliberately skipped for multi-member mixed-direction
    # events (the prompt's own "pick the member closest to its own
    # floor" instruction means the sentence legitimately describes only
    # one member, not a resolvable "the event's" direction).
    if len(real_move_bps) == 1 and real_move_bps[0] != 0:
        lowered = transmission.lower()
        said_rise = any(w in lowered for w in _RISE_WORDS)
        said_fall = any(w in lowered for w in _FALL_WORDS)
        if said_rise and said_fall:
            pass  # ambiguous wording (e.g. "fell before rising") - not this check's job to parse
        elif said_rise and real_move_bps[0] < 0:
            problems.append(f"transmission uses a rise word but the real move_bp is negative ({real_move_bps[0]})")
        elif said_fall and real_move_bps[0] > 0:
            problems.append(f"transmission uses a fall word but the real move_bp is positive ({real_move_bps[0]})")

    return FactCheckResult(ok=not problems, problems=problems)
