"""Suppression mechanisms A (derived series) and B (collinear clusters) for
the Macro Signal Backbone spec (section 5). Mechanism C (confirmation
reversal) lives in macro_signal_confirmation.py - it's retroactive (needs a
later observation) and runs as its own pass once a later observation has
arrived, not in the same run as A/B.

Order matters: A, then B. Nothing is ever deleted - suppressed rows are
annotated with `suppressed_by`, tier is left untouched.

Validated standalone against real FRED data (DGS10 = DFII10 + T10YIE
identity, residual 0.000000) before being ported into this service - see
project memory / plan history for the validation script.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from pipeline.macro_signal_thresholds import Tier, TierResult


@dataclass
class SuppressibleResult:
    """TierResult plus the suppression annotation and the raw value/date
    needed to check derived-series identities and collinear-cluster
    membership.

    source and knowledge_time_confidence are carried through from the
    underlying news-retrieval macro_observations row (see
    macro_signal_fetch.py / macro_release_times.py there) rather than
    recomputed here - this is provenance about where the number came
    from and how certain its publication timing is, not something this
    layer can determine on its own.

    move_bp is the real day-over-day change (d1d_bp) for a standard
    series, or the SEP median shift (sep_median_shift_bp) for FEDTARMD -
    whichever number tiering actually keyed its HIGH/WEAK decision on.
    Kept distinct from `value` (the raw level, needed for derived-series
    identity checks like DGS10 = DFII10 + T10YIE) because CONFIRMED LIVE:
    without a real move field, INTERPRET was only ever given `value` and
    silently misread the LEVEL as if it were the move (e.g. T10Y2Y's
    level 0.31 reported as "steepened by 31bp" when the real move was
    +5bp; FEDTARMD with no move field at all fabricated "375bp" from
    nothing traceable) - see project plan history for the live audit
    that found this."""
    series_id: str
    tier: Tier
    z_score: Optional[float]
    reason: str
    value: Optional[float] = None          # native-unit level, needed for identity checks
    move_bp: Optional[float] = None        # real change (d1d_bp or sep_median_shift_bp) - what INTERPRET should call "the move"
    target_year: Optional[int] = None      # FEDTARMD-only: which projected year move_bp/value refer to (CONFIRMED LIVE gap: a frontend consuming a FEDTARMD event had no field saying which year "the medium-run fed funds target" meant)
    suppressed_by: Optional[str] = None
    source: Optional[str] = None                       # 'fred' | 'fred_alfred' | 'treasury_fiscal'
    knowledge_time_confidence: Optional[str] = None     # 'verified' | 'known_lag'


def from_tier_result(
    tr: TierResult, value: Optional[float] = None,
    *, move_bp: Optional[float] = None, target_year: Optional[int] = None,
    source: Optional[str] = None, knowledge_time_confidence: Optional[str] = None,
) -> SuppressibleResult:
    return SuppressibleResult(
        tr.series_id, tr.tier, tr.z_score, tr.reason, value=value, move_bp=move_bp,
        target_year=target_year, source=source, knowledge_time_confidence=knowledge_time_confidence,
    )


# Mechanism A: derived-series arithmetic identities.
# "legs" fired means the LEG series itself is HIGH or WEAK (not NOISE) on
# the same date - a leg suppressed by mechanism A itself doesn't count for
# a downstream identity (there's only one derived level here, so this
# doesn't recurse in the current 46-series set).
_DERIVED_IDENTITIES = [
    {"derived": "DGS10", "legs": ["DFII10", "T10YIE"], "mode": "either_leg_fired"},
    {"derived": "T10Y2Y", "legs": ["DGS10", "DGS2"], "mode": "both_legs_fired"},
    {"derived": "T10Y3M", "legs": ["DGS10", "DGS3MO"], "mode": "both_legs_fired"},
    {"derived": "PCEPILFE", "legs": ["CPILFESL"], "mode": "either_leg_fired"},
]

# Mechanism B: collinear clusters - keep highest |z| if >=1 member is HIGH.
_COLLINEAR_CLUSTERS = [
    {"members": ["DGS3MO", "DGS1", "DGS2"]},
    {"members": ["BAA10Y", "NFCI", "ANFCI", "NFCICREDIT"]},
    {"members": ["PAYEMS", "UNRATE", "SAHMREALTIME"]},
    {"members": ["CPIAUCSL", "CPILFESL"], "prefer": "CPILFESL"},
    {"members": ["HOUST", "PERMIT"]},
    {"members": ["ICSA", "CCSA"]},
    {"members": ["VIXCLS", "VXVCLS"]},
]


def _fired(r: SuppressibleResult) -> bool:
    return r.tier in (Tier.HIGH, Tier.WEAK) and r.suppressed_by is None


def apply_derived_suppression(results: dict[str, SuppressibleResult]) -> None:
    """Mutates results in place - sets suppressed_by on any derived series
    whose identity condition is met by its legs' fired status."""
    for identity in _DERIVED_IDENTITIES:
        derived_id = identity["derived"]
        derived = results.get(derived_id)
        if derived is None or not _fired(derived):
            continue
        legs = [results.get(lid) for lid in identity["legs"]]
        legs_fired = [l is not None and _fired(l) for l in legs]
        if identity["mode"] == "either_leg_fired" and any(legs_fired):
            derived.suppressed_by = f"derived:{'+'.join(identity['legs'])}"
        elif identity["mode"] == "both_legs_fired" and all(legs_fired):
            derived.suppressed_by = f"derived:{'+'.join(identity['legs'])}"


def apply_collinear_suppression(results: dict[str, SuppressibleResult]) -> None:
    """Mutates results in place. For each cluster, if >=1 member is HIGH,
    keep the highest-|z| member (or the `prefer`-named member if the spec
    names a tie-breaker preference), suppress the rest. If no member is
    HIGH, do nothing - two moderate legs must not suppress each other,
    since that could hide a genuinely large move in the spread between them.
    """
    for cluster in _COLLINEAR_CLUSTERS:
        member_ids = cluster["members"]
        members = [(mid, results.get(mid)) for mid in member_ids]
        fired_members = [(mid, r) for mid, r in members if r is not None and _fired(r)]
        if len(fired_members) < 2:
            continue  # need at least 2 firing to have a duplicate to suppress
        if not any(r.tier == Tier.HIGH for _, r in fired_members):
            continue  # spec's explicit condition: >=1 must be HIGH

        prefer = cluster.get("prefer")
        if prefer and any(mid == prefer for mid, _ in fired_members):
            keep_id = prefer
        else:
            keep_id = max(fired_members, key=lambda mr: abs(mr[1].z_score or 0.0))[0]

        for mid, r in fired_members:
            if mid != keep_id:
                r.suppressed_by = f"collinear:{keep_id}"
