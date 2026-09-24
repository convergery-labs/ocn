"""Suppression mechanism C (spec section 5): confirmation reversal.

For weekly/monthly series, a move that FULLY reverses at the next
observation is retroactively reclassified NOISE (suppressed_by set on the
ORIGINAL event, not skipped at emission time - the original event may
already have been collapsed/interpreted by the time the reversal is
knowable, since a monthly series' next print is up to ~4 weeks later).

This is why mechanism C is structurally different from A/B: it cannot run
in the same pass as tier/suppress/collapse, because the confirming
observation doesn't exist yet at that point. It's a separate, later pass
that re-examines already-tiered events once a next observation has arrived.

"Fully reverses" is interpreted here as: the next observation's change has
the opposite sign AND a magnitude >= the original move's magnitude (i.e.
it doesn't just partially retrace - it erases the original move entirely,
consistent with the spec's own examples: "Claims rose 28k, reversed the
following week" -> no event, vs. a move that stands should still count).
A partial reversal (same or smaller magnitude, or same-sign continuation)
must NOT suppress - only a genuine round-trip does.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ConfirmationCheck:
    series_id: str
    original_change: float
    next_change: Optional[float]
    reversed: bool
    reason: str


def check_confirmation_reversal(
    series_id: str, original_change: float, next_change: Optional[float],
) -> ConfirmationCheck:
    if next_change is None:
        return ConfirmationCheck(series_id, original_change, None, False, "no_next_observation_yet")

    opposite_sign = (original_change > 0 and next_change < 0) or (original_change < 0 and next_change > 0)
    if not opposite_sign:
        return ConfirmationCheck(series_id, original_change, next_change, False, "same_sign_or_no_reversal")

    fully_reversed = abs(next_change) >= abs(original_change)
    if fully_reversed:
        return ConfirmationCheck(
            series_id, original_change, next_change, True,
            f"full_reversal: original={original_change:+.2f}, next={next_change:+.2f}",
        )
    return ConfirmationCheck(
        series_id, original_change, next_change, False,
        f"partial_reversal_only: original={original_change:+.2f}, next={next_change:+.2f} (must NOT suppress)",
    )
