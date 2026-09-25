"""Post-INTERPRET numeric fact-check (spec follow-up, real frontend
ticket item 7, 2026-09-25): "All numbers must be correct and consistent
with each other." The original "31bp for a 5bp move" bug (T10Y2Y) would
have been caught by this - the LLM was free to write any bp figure in
`transmission`, and nothing checked it against the real move_bp before
the row was stored.

Scope: this checks what is mechanically checkable - every bp number
written in `transmission` must appear (within rounding tolerance) among
the real move_bp values for this event's members, and every member's
OWN direction (up/down) must agree with its real move_bp sign. It does
NOT check % level references, since a native-unit level appears in free
text in too many forms (e.g. "6.95%" vs "rose to 6.95") to match
reliably without false positives - flagged as a known gap, not silently
ignored.

Does not check cross-event aggregate counts (HIGH/WEAK/NOISE/suppressed
totals matching /results) - that is a property of the whole run's output,
not of one event, and belongs in a separate post-run check, not here.

HISTORY (why direction is no longer parsed from free text): two real
bugs were found live parsing direction words out of `transmission`
prose (2026-09-25, jobs 267 and 271) - first, a check that only
validated single-member events missed a wrong-direction word on a
multi-member sentence; then, a per-number match picked the FIRST real
member matching a written |value|, which silently gave a WRONG verdict
whenever two members shared the same |move_bp| with OPPOSITE signs
(DFII10 +8bp and T10Y2Y -8bp in one real event - "steepening... by
8bp" matched DFII10 and passed, when the sentence meant T10Y2Y). No
free-text heuristic can reliably resolve that tie - which series a
number refers to is fundamentally not recoverable from the digits
alone. Fixed at the root instead: INTERPRET's own output now includes
series_directions (a per-series up/down map the model states
directly, see macro_signal_interpret_v1.txt), so this module checks
real structured data against real move_bp, never prose.
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
    against the real move_bp values - number correctness only (never
    ambiguous: either some member's move_bp is within tolerance of the
    written value, or it isn't). Direction is checked separately by
    check_series_directions_match_real_signs, against the model's own
    structured series_directions field, not by parsing this text.
    """
    problems: list[str] = []
    real_move_bps = [m["move_bp"] for m in members if m.get("move_bp") is not None]

    for match in _BP_NUMBER_RE.finditer(transmission):
        written = float(match.group(1))
        if not any(abs(abs(written) - abs(real)) <= _BP_MATCH_TOLERANCE for real in real_move_bps):
            problems.append(
                f"transmission cites {written}bp, but no member's real move_bp is within "
                f"{_BP_MATCH_TOLERANCE}bp of it (real values: {real_move_bps})"
            )

    return FactCheckResult(ok=not problems, problems=problems)


def check_series_directions_match_real_signs(
    series_directions: dict[str, str], members: list[dict[str, Any]],
) -> FactCheckResult:
    """series_directions: the model's own {series_id: "up"|"down"} map
    (macro_signal_interpret_v1.txt's own required field). Checks each
    member's stated direction against its real move_bp sign directly -
    no text parsing, no ambiguity: this is the fix for the real
    coincidental-tie bug free-text parsing could never fully resolve
    (see this module's own docstring)."""
    problems: list[str] = []
    real_move_bp_by_series = {m["series_id"]: m["move_bp"] for m in members if m.get("move_bp") is not None}

    for series_id, real_move_bp in real_move_bp_by_series.items():
        if real_move_bp == 0:
            continue  # no real direction to check against a flat move
        stated = series_directions.get(series_id)
        if stated is None:
            problems.append(f"series_directions is missing {series_id!r} (real move_bp={real_move_bp})")
            continue
        real_direction = "up" if real_move_bp > 0 else "down"
        if stated != real_direction:
            problems.append(
                f"series_directions says {series_id!r} is {stated!r}, but its real move_bp is "
                f"{real_move_bp} ({real_direction})"
            )

    return FactCheckResult(ok=not problems, problems=problems)
