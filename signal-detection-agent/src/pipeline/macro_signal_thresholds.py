"""46-series threshold table for the Macro Signal Backbone spec (section 7),
plus the 7-channel membership (per-channel series list) and the 2
z-gate-exception series (FEDTARMD, DFF) and 1 tiering-exclusion (DFEDTARU).

Standalone module - no DB, no HTTP, no service dependency. This is the
validated basis for signal-detection-agent's future
pipeline/macro_signal_thresholds.py, built and unit-tested here first per
the project's step-by-step validation approach.

Each series' rule is NOT uniform arithmetic - some are bp thresholds on
|d1d|, some are % thresholds against a trailing average, some are level
crossings, some are compound AND/OR conditions with z-gates on a derived
quantity (e.g. VXVCLS's ratio). So THRESHOLDS holds one SeriesRule per
series, each carrying a small `evaluate()` callable rather than trying to
force every series into identical numeric fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class Channel(str, Enum):
    POLICY_PATH = "policy_path"
    DISCOUNT_RATE = "discount_rate"
    CREDIT = "credit"
    LIQUIDITY = "liquidity"
    REAL_ECONOMY = "real_economy"
    CURRENCY = "currency"
    RISK_APPETITE = "risk_appetite"


class Tier(str, Enum):
    HIGH = "HIGH"
    WEAK = "WEAK"
    NOISE = "NOISE"


@dataclass
class SeriesMove:
    """Everything a rule needs to evaluate one series on one date.
    Only the fields relevant to that series' rule need be populated by the
    caller; unused fields are simply ignored by a given evaluate() fn.
    """
    series_id: str
    d1d_bp: Optional[float] = None          # 1-day change, native bp
    d1w_bp: Optional[float] = None           # 1-week change, native bp
    d4w_bp: Optional[float] = None           # 4-week change, native bp/pp/$ (unit is series-specific, see docstring per rule)
    d4w_pct: Optional[float] = None          # 4-week change as % of level (e.g. TOTRESNS)
    d3m_pct: Optional[float] = None          # 3-month change as % of level
    dm_pp: Optional[float] = None            # month-over-month change, percentage points
    dm_vs_trailing_pp: Optional[float] = None  # month-over-month change minus trailing-12m avg m/m, pp
    dq_pp: Optional[float] = None            # quarter-over-quarter change, pp
    level: Optional[float] = None            # current level (for level-crossing rules)
    prior_level: Optional[float] = None      # prior period level (for sign-flip/crossing detection)
    z: Optional[float] = None                # z-score on the primary quantity this rule gates on
    net_revision_k: Optional[float] = None   # PAYEMS-specific: revision to prior 2 months, thousands
    sign_flip: bool = False                  # True if the spread's sign flipped this period (T10Y2Y/T10Y3M)
    is_inter_meeting_date: bool = False       # DFF-specific: target moved on a non-FOMC date
    sep_median_shift_bp: Optional[float] = None  # FEDTARMD-specific: next-yr median vs prior SEP, bp
    ratio: Optional[float] = None            # VIXCLS/VXVCLS-specific: the ratio value
    ratio_d1d_pct: Optional[float] = None    # VIXCLS/VXVCLS-specific: 1-day % change in the ratio


@dataclass
class TierResult:
    series_id: str
    tier: Tier
    z_score: Optional[float]
    reason: str  # self-describing, e.g. "abs_d1d_12bp_ge_floor_and_z_2.30" - kept as-is for debugging (real ask, frontend ticket 2026-09-25)
    plain_reason: Optional[str] = None  # human-readable sentence, e.g. "1-day move of 13bp cleared the 10bp HIGH floor (z = +2.61)." - written inline in each rule's own branch, NOT derived by parsing `reason`, so it always matches the exact logic that ran. None on a NOISE/missing-data result (nothing worth explaining to a reader).


EvalFn = Callable[[SeriesMove], TierResult]


def _abs_d1d_rule(high_bp: float, weak_bp: float) -> EvalFn:
    """Generic rule shape: |d1d| >= high_bp AND z>=2.0 -> HIGH;
    |d1d| >= weak_bp AND z>=1.0 -> WEAK. Covers DFII10, DFII5, T10YIE,
    T5YIFR, DGS10, DGS3MO, DGS2, DGS1 (8 of the 46 series share this exact
    shape - validated live against DFII5/DGS1/DGS10/DFII10/T10YIE in Step 0)."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.d1d_bp is None or m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        a = abs(m.d1d_bp)
        if a >= high_bp and abs(m.z) >= 2.0:
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"abs_d1d_{a:.1f}bp_ge_{high_bp}_z_{m.z:.2f}",
                plain_reason=f"1-day move of {a:.0f}bp cleared the {high_bp:.0f}bp HIGH floor (z = {m.z:+.2f}).",
            )
        if a >= weak_bp and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"abs_d1d_{a:.1f}bp_ge_{weak_bp}_z_{m.z:.2f}",
                plain_reason=f"1-day move of {a:.0f}bp cleared the {weak_bp:.0f}bp WEAK floor (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, f"abs_d1d_{a:.1f}bp_below_floor")
    return _eval


def _abs_d1d_or_sign_flip_rule(high_bp: float, weak_bp: float) -> EvalFn:
    """T10Y2Y / T10Y3M: |d1d| >= floor OR sign flips -> HIGH gate (still needs z>=2.0)."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.d1d_bp is None or m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        a = abs(m.d1d_bp)
        high_gate = a >= high_bp or m.sign_flip
        weak_gate = a >= weak_bp
        if high_gate and abs(m.z) >= 2.0:
            if m.sign_flip:
                plain = f"The spread crossed zero (curve un-inverted), which counts as HIGH on its own (z = {m.z:+.2f})."
            else:
                plain = f"1-day move of {a:.0f}bp cleared the {high_bp:.0f}bp HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"abs_d1d_{a:.1f}bp_or_signflip({m.sign_flip})_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if weak_gate and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"abs_d1d_{a:.1f}bp_weak_z_{m.z:.2f}",
                plain_reason=f"1-day move of {a:.0f}bp cleared the {weak_bp:.0f}bp WEAK floor (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, f"abs_d1d_{a:.1f}bp_below_floor")
    return _eval


def _d1d_or_d1w_or_level_rule(
    d1d_high: float, d1w_high: float, level_high: float,
    d1d_weak_lo: float, d1d_weak_hi: float, level_weak_lo: float, level_weak_hi: float,
) -> EvalFn:
    """BAA10Y shape: (|d1d|>=X or |d1w|>=Y or level>=Z) AND z>=2.0 -> HIGH;
    (d1d in weak band or level in weak band) AND z>=1.0 -> WEAK."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        a = abs(m.d1d_bp) if m.d1d_bp is not None else 0.0
        w = abs(m.d1w_bp) if m.d1w_bp is not None else 0.0
        lvl = m.level if m.level is not None else float("-inf")
        high_gate = a >= d1d_high or w >= d1w_high or lvl >= level_high
        weak_gate = (d1d_weak_lo <= a < d1d_weak_hi) or (level_weak_lo <= lvl < level_weak_hi)
        if high_gate and abs(m.z) >= 2.0:
            if a >= d1d_high:
                plain = f"1-day move of {a:.0f}bp cleared the {d1d_high:.0f}bp HIGH floor (z = {m.z:+.2f})."
            elif w >= d1w_high:
                plain = f"1-week move of {w:.0f}bp cleared the {d1w_high:.0f}bp HIGH floor (z = {m.z:+.2f})."
            else:
                plain = f"Level of {lvl:.2f} cleared the {level_high:.2f} HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"d1d_{a:.1f}bp_or_d1w_{w:.1f}bp_or_level_{lvl:.2f}_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if weak_gate and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"weak_band_z_{m.z:.2f}",
                plain_reason=f"Move fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _level_cross_or_d4w_rule(cross_level: float, d4w_high: float, d4w_weak_lo: float, d4w_weak_hi: float, level_weak_lo: float, level_weak_hi: float) -> EvalFn:
    """NFCI shape: level crosses above cross_level OR d4w>=d4w_high -> HIGH gate."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        crossed = (m.prior_level is not None and m.level is not None
                   and m.prior_level < cross_level <= m.level)
        d4w = m.d4w_bp if m.d4w_bp is not None else 0.0
        high_gate = crossed or d4w >= d4w_high
        weak_gate = (d4w_weak_lo <= d4w < d4w_weak_hi) or (
            m.level is not None and level_weak_lo <= m.level < level_weak_hi
        )
        if high_gate and abs(m.z) >= 2.0:
            if crossed:
                plain = f"Level crossed above {cross_level:.2f}, which counts as HIGH on its own (z = {m.z:+.2f})."
            else:
                plain = f"4-week move of {d4w:.0f}bp cleared the {d4w_high:.0f}bp HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"level_cross({crossed})_or_d4w_{d4w:.3f}_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if weak_gate and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"weak_band_z_{m.z:.2f}",
                plain_reason=f"Move fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _level_or_d4w_rule(level_high: float, d4w_high: float, level_weak_lo: float, level_weak_hi: float, d4w_weak_lo: float, d4w_weak_hi: float) -> EvalFn:
    """ANFCI / NFCICREDIT shape: level>=X OR d4w>=Y -> HIGH gate (no cross detection)."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        lvl = m.level if m.level is not None else float("-inf")
        d4w = m.d4w_bp if m.d4w_bp is not None else 0.0
        high_gate = lvl >= level_high or d4w >= d4w_high
        weak_gate = (level_weak_lo <= lvl < level_weak_hi) or (d4w_weak_lo <= d4w < d4w_weak_hi)
        if high_gate and abs(m.z) >= 2.0:
            if lvl >= level_high:
                plain = f"Level of {lvl:.2f} cleared the {level_high:.2f} HIGH floor (z = {m.z:+.2f})."
            else:
                plain = f"4-week move of {d4w:.0f}bp cleared the {d4w_high:.0f}bp HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"level_{lvl:.3f}_or_d4w_{d4w:.3f}_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if weak_gate and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"weak_band_z_{m.z:.2f}",
                plain_reason=f"Move fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _level_or_dq_rule(level_high: float, dq_high: float, level_weak_lo: float, level_weak_hi: float, dq_weak_lo: float, dq_weak_hi: float) -> EvalFn:
    """DRTSCILM shape: level>=X OR dq>=Y (pp) -> HIGH gate."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        lvl = m.level if m.level is not None else float("-inf")
        dq = m.dq_pp if m.dq_pp is not None else 0.0
        high_gate = lvl >= level_high or dq >= dq_high
        weak_gate = (level_weak_lo <= lvl < level_weak_hi) or (dq_weak_lo <= dq < dq_weak_hi)
        if high_gate and abs(m.z) >= 2.0:
            if lvl >= level_high:
                plain = f"Level of {lvl:.2f} cleared the {level_high:.2f} HIGH floor (z = {m.z:+.2f})."
            else:
                plain = f"Quarter-over-quarter move of {dq:.2f}pp cleared the {dq_high:.2f}pp HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"level_{lvl:.2f}_or_dq_{dq:.2f}pp_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if weak_gate and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"weak_band_z_{m.z:.2f}",
                plain_reason=f"Move fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _abs_d4w_rule(high: float, weak_lo: float, weak_hi: float, *, unit: str = "$bn") -> EvalFn:
    """WALCL/RRPONTSYD/WTREGEN/WRESBAL shape: |d4w| >= high AND z>=2.0 -> HIGH."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.d4w_bp is None or m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        a = abs(m.d4w_bp)
        if a >= high and abs(m.z) >= 2.0:
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"abs_d4w_{a:.1f}{unit}_ge_{high}_z_{m.z:.2f}",
                plain_reason=f"4-week move of {a:.0f}{unit} cleared the {high:.0f}{unit} HIGH floor (z = {m.z:+.2f}).",
            )
        if weak_lo <= a < weak_hi and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"abs_d4w_{a:.1f}{unit}_weak_z_{m.z:.2f}",
                plain_reason=f"4-week move of {a:.0f}{unit} fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, f"abs_d4w_{a:.1f}{unit}_below_floor")
    return _eval


def _abs_pct_rule(field_name: str, high: float, weak_lo: float, weak_hi: float) -> EvalFn:
    """Generic |pct-change-of-some-kind| >= X% rule, reading from
    d3m_pct/d4w_pct/dm_vs_trailing_pp per field_name. Covers TOTRESNS
    (d3m_pct), DTWEXBGS (special-cased separately, has an OR clause),
    JTSJOL (d3m_pct), RSAFS (dm_pp used as pct here), etc."""
    def _eval(m: SeriesMove) -> TierResult:
        val = getattr(m, field_name)
        if val is None or m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        a = abs(val)
        if a >= high and abs(m.z) >= 2.0:
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"abs_{field_name}_{a:.2f}_ge_{high}_z_{m.z:.2f}",
                plain_reason=f"Move of {a:.2f}% cleared the {high:.2f}% HIGH floor (z = {m.z:+.2f}).",
            )
        if weak_lo <= a < weak_hi and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"abs_{field_name}_{a:.2f}_weak_z_{m.z:.2f}",
                plain_reason=f"Move of {a:.2f}% fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, f"abs_{field_name}_{a:.2f}_below_floor")
    return _eval


def _dtwexbgs_rule() -> EvalFn:
    """DTWEXBGS: |d1d|>=0.75% OR |d4w|>=2.5% -> HIGH; d1d 0.35-0.75% -> WEAK."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        d1d = abs(m.d1d_bp) if m.d1d_bp is not None else 0.0  # reused field, holds pct here (native unit)
        d4w = abs(m.d4w_pct) if m.d4w_pct is not None else 0.0
        if (d1d >= 0.75 or d4w >= 2.5) and abs(m.z) >= 2.0:
            if d1d >= 0.75:
                plain = f"1-day move of {d1d:.2f}% cleared the 0.75% HIGH floor (z = {m.z:+.2f})."
            else:
                plain = f"4-week move of {d4w:.2f}% cleared the 2.5% HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"d1d_{d1d:.2f}pct_or_d4w_{d4w:.2f}pct_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if 0.35 <= d1d < 0.75 and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"d1d_{d1d:.2f}pct_weak_z_{m.z:.2f}",
                plain_reason=f"1-day move of {d1d:.2f}% fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _payems_rule() -> EvalFn:
    """PAYEMS: |dm - trailing12m avg dm| >= 347k OR net revision to prior 2 months >= +-100k -> HIGH."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.dm_vs_trailing_pp is None or m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        dev = abs(m.dm_vs_trailing_pp)  # holds thousands here, not pp, for this series
        rev = abs(m.net_revision_k) if m.net_revision_k is not None else 0.0
        if (dev >= 347 or rev >= 100) and abs(m.z) >= 2.0:
            if dev >= 347:
                plain = f"Payrolls came in {dev:.0f}k off the trailing 12-month average, above the 347k HIGH floor (z = {m.z:+.2f})."
            else:
                plain = f"Prior 2 months revised a net {rev:.0f}k, above the 100k HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"dev_{dev:.0f}k_or_rev_{rev:.0f}k_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if 50 <= dev < 347 and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"dev_{dev:.0f}k_weak_z_{m.z:.2f}",
                plain_reason=f"Payrolls came in {dev:.0f}k off the trailing 12-month average, in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _unrate_rule() -> EvalFn:
    """UNRATE: dm >= +0.3pp (signed, not abs) AND z>=2.0 -> HIGH."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.dm_pp is None or m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        if m.dm_pp >= 0.3 and m.z >= 2.0:
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"dm_{m.dm_pp:.2f}pp_ge_0.3_z_{m.z:.2f}",
                plain_reason=f"Month-over-month rise of {m.dm_pp:.2f}pp cleared the 0.30pp HIGH floor (z = {m.z:+.2f}).",
            )
        if abs(m.dm_pp) >= 0.1 and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"dm_{m.dm_pp:.2f}pp_weak_z_{m.z:.2f}",
                plain_reason=f"Month-over-month move of {m.dm_pp:+.2f}pp fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _sahm_rule() -> EvalFn:
    """SAHMREALTIME: level crosses >= 0.50 (published trigger) -> HIGH; 0.30-0.50 -> WEAK. No z-gate stated for this one in the spec's own phrasing ("crosses the published trigger") - treated as z-gated per the universal rule since no exception is documented for SAHMREALTIME specifically (only FEDTARMD and DFF are named exceptions)."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.level is None or m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        if m.level >= 0.50 and abs(m.z) >= 2.0:
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"level_{m.level:.2f}_ge_0.50_z_{m.z:.2f}",
                plain_reason=f"Sahm indicator reached {m.level:.2f}, at or above the 0.50 HIGH recession-trigger level (z = {m.z:+.2f}).",
            )
        if 0.30 <= m.level < 0.50 and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"level_{m.level:.2f}_weak_z_{m.z:.2f}",
                plain_reason=f"Sahm indicator reached {m.level:.2f}, in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _hous_style_rule(high3m: float, high1m: float, weak1m_lo: float, weak1m_hi: float) -> EvalFn:
    """HOUST: |3mo avg change| >= 8% OR single month |change| >= 15% -> HIGH."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        d3m = abs(m.d3m_pct) if m.d3m_pct is not None else 0.0
        dm = abs(m.dm_pp) if m.dm_pp is not None else 0.0
        if (d3m >= high3m or dm >= high1m) and abs(m.z) >= 2.0:
            if d3m >= high3m:
                plain = f"3-month average change of {d3m:.2f}% cleared the {high3m:.2f}% HIGH floor (z = {m.z:+.2f})."
            else:
                plain = f"Single-month change of {dm:.2f}% cleared the {high1m:.2f}% HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"d3m_{d3m:.2f}pct_or_dm_{dm:.2f}pct_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if weak1m_lo <= dm < weak1m_hi and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"dm_{dm:.2f}pct_weak_z_{m.z:.2f}",
                plain_reason=f"Single-month change of {dm:.2f}% fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _csushpinsa_rule() -> EvalFn:
    """CSUSHPINSA: y/y crosses zero OR |d3m annualised - trailing| >= 10pp -> HIGH."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        crossed = (m.prior_level is not None and m.level is not None
                   and (m.prior_level < 0 <= m.level or m.prior_level > 0 >= m.level))
        dev = abs(m.dm_vs_trailing_pp) if m.dm_vs_trailing_pp is not None else 0.0
        if (crossed or dev >= 10) and abs(m.z) >= 2.0:
            if crossed:
                plain = f"Year-over-year home price growth crossed zero, which counts as HIGH on its own (z = {m.z:+.2f})."
            else:
                plain = f"3-month annualized change deviated {dev:.2f}pp from trend, above the 10pp HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"yoy_cross({crossed})_or_dev_{dev:.2f}pp_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if 2 <= dev < 10 and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"dev_{dev:.2f}pp_weak_z_{m.z:.2f}",
                plain_reason=f"3-month annualized change deviated {dev:.2f}pp from trend, in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _drcclacbs_rule() -> EvalFn:
    """DRCCLACBS: dq >= +0.25pp OR level >= 3.5% -> HIGH."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        dq = m.dq_pp if m.dq_pp is not None else float("-inf")
        lvl = m.level if m.level is not None else float("-inf")
        if (dq >= 0.25 or lvl >= 3.5) and abs(m.z) >= 2.0:
            if dq >= 0.25:
                plain = f"Quarter-over-quarter rise of {dq:.2f}pp cleared the 0.25pp HIGH floor (z = {m.z:+.2f})."
            else:
                plain = f"Level of {lvl:.2f}% cleared the 3.5% HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"dq_{dq:.2f}pp_or_level_{lvl:.2f}_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if 0.10 <= dq < 0.25 and abs(m.z) >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"dq_{dq:.2f}pp_weak_z_{m.z:.2f}",
                plain_reason=f"Quarter-over-quarter move of {dq:.2f}pp fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor")
    return _eval


def _vix_rule() -> EvalFn:
    """VIXCLS: (d1d>=+20% OR level>=30) AND z>=2.0 on OWN daily % changes -> HIGH.
    Explicitly asymmetric - a large DROP never triggers HIGH, only a spike.
    d1d_bp field reused to carry pct here (matches DTWEXBGS's convention)."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.z is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        d1d = m.d1d_bp if m.d1d_bp is not None else 0.0  # signed - only a positive spike counts
        lvl = m.level if m.level is not None else float("-inf")
        if (d1d >= 20 or lvl >= 30) and m.z >= 2.0:
            if d1d >= 20:
                plain = f"VIX spiked {d1d:.1f}% in one day, above the 20% HIGH floor (z = {m.z:+.2f})."
            else:
                plain = f"VIX level of {lvl:.1f} cleared the 30 HIGH floor (z = {m.z:+.2f})."
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"d1d_{d1d:.1f}pct_or_level_{lvl:.1f}_z_{m.z:.2f}",
                plain_reason=plain,
            )
        if (10 <= d1d < 20 or 20 <= lvl < 30) and m.z >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"weak_band_z_{m.z:.2f}",
                plain_reason=f"VIX move fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "below_floor_or_not_a_spike")
    return _eval


def _vxv_ratio_rule() -> EvalFn:
    """VXVCLS, evaluated as VIXCLS/VXVCLS ratio: (ratio>=1.00, inversion) AND
    z>=2.0 on the RATIO's own daily change -> HIGH. Only emitted once per
    the spec's collinear-cluster rule (suppression mechanism B handles the
    "emit one" part; this function only tiers the ratio itself)."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.z is None or m.ratio is None:
            return TierResult(m.series_id, Tier.NOISE, m.z, "missing_data")
        if m.ratio >= 1.00 and m.z >= 2.0:
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"ratio_{m.ratio:.3f}_inverted_z_{m.z:.2f}",
                plain_reason=f"VIX/VXV ratio inverted to {m.ratio:.3f} (>= 1.00), a near-term volatility spike that counts as HIGH (z = {m.z:+.2f}).",
            )
        if 0.95 <= m.ratio < 1.00 and m.z >= 1.0:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"ratio_{m.ratio:.3f}_weak_z_{m.z:.2f}",
                plain_reason=f"VIX/VXV ratio of {m.ratio:.3f} fell in this series' WEAK band (z = {m.z:+.2f}).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "not_inverted")
    return _eval


def _dff_rule() -> EvalFn:
    """DFF: two independent HIGH paths. (i) inter-meeting move - date-match
    only, NO size threshold, NO z-gate (an emergency Fed move is an event
    by definition). (ii) |d1d|>=27bp AND z>=2.0. Spec's own sanity bound:
    ~9 inter-meeting moves since 1994 - if this fires far more often than
    that historically, the inter-meeting DATE detection itself is broken,
    not this tier function."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.is_inter_meeting_date:
            return TierResult(
                m.series_id, Tier.HIGH, m.z, "inter_meeting_move_no_gate",
                plain_reason="The Fed funds target moved outside a scheduled FOMC meeting - an inter-meeting move counts as HIGH on its own (no size or z-score check).",
            )
        if m.d1d_bp is not None and m.z is not None and abs(m.d1d_bp) >= 27 and abs(m.z) >= 2.0:
            return TierResult(
                m.series_id, Tier.HIGH, m.z, f"abs_d1d_{abs(m.d1d_bp):.1f}bp_ge_27_z_{m.z:.2f}",
                plain_reason=f"1-day move of {abs(m.d1d_bp):.0f}bp cleared the 27bp HIGH floor (z = {m.z:+.2f}).",
            )
        d = abs(m.d1d_bp) if m.d1d_bp is not None else 0.0
        if 2 <= d <= 27:
            return TierResult(
                m.series_id, Tier.WEAK, m.z, f"drift_{d:.1f}bp_within_range",
                plain_reason=f"1-day move of {d:.0f}bp was within the 2-27bp WEAK range (no z-score check).",
            )
        return TierResult(m.series_id, Tier.NOISE, m.z, "no_move")
    return _eval


def _fedtarmd_rule() -> EvalFn:
    """FEDTARMD: next-year median shift >= 25bp vs prior SEP -> HIGH.
    NO z-gate (only 4 prints/year - a rolling window is meaningless per spec)."""
    def _eval(m: SeriesMove) -> TierResult:
        if m.sep_median_shift_bp is None:
            return TierResult(m.series_id, Tier.NOISE, None, "missing_data")
        a = abs(m.sep_median_shift_bp)
        if a >= 25:
            return TierResult(
                m.series_id, Tier.HIGH, None, f"sep_median_shift_{a:.1f}bp_ge_25_no_zgate",
                plain_reason=f"The SEP median moved {a:.0f}bp, above the 25bp HIGH threshold (no z-score check).",
            )
        if a > 0:
            return TierResult(
                m.series_id, Tier.WEAK, None, f"median_flat_or_dispersion_shift_{a:.1f}bp",
                plain_reason=f"The SEP median moved {a:.0f}bp, below the 25bp HIGH threshold (no z-score check).",
            )
        return TierResult(m.series_id, Tier.NOISE, None, "no_shift")
    return _eval


@dataclass
class SeriesRule:
    series_id: str
    channel: Channel
    evaluate: EvalFn
    high_rule_desc: str
    weak_rule_desc: str


THRESHOLDS: dict[str, SeriesRule] = {}


def _register(series_id: str, channel: Channel, evaluate: EvalFn, high_desc: str, weak_desc: str) -> None:
    THRESHOLDS[series_id] = SeriesRule(series_id, channel, evaluate, high_desc, weak_desc)


# --- Background state variables (24), minus DFEDTARU (excluded) ---
_register("DFII10", Channel.DISCOUNT_RATE, _abs_d1d_rule(10, 5), "|d1d|>=10bp", "5-10bp")
_register("DFII5", Channel.DISCOUNT_RATE, _abs_d1d_rule(10, 5), "|d1d|>=10bp", "5-10bp")
_register("T10YIE", Channel.DISCOUNT_RATE, _abs_d1d_rule(6, 3), "|d1d|>=6bp", "3-6bp")
_register("T5YIFR", Channel.DISCOUNT_RATE, _abs_d1d_rule(6, 3), "|d1d|>=6bp", "3-6bp")
_register("T10Y2Y", Channel.DISCOUNT_RATE, _abs_d1d_or_sign_flip_rule(8, 4), "|d1d|>=8bp or sign flip", "4-8bp")
_register("T10Y3M", Channel.DISCOUNT_RATE, _abs_d1d_or_sign_flip_rule(10, 5), "|d1d|>=10bp or sign flip", "5-10bp")
_register("DGS10", Channel.DISCOUNT_RATE, _abs_d1d_rule(12, 6), "|d1d|>=12bp", "6-12bp")
_register("DGS3MO", Channel.POLICY_PATH, _abs_d1d_rule(8, 3), "|d1d|>=8bp", "3-8bp")
_register("DGS2", Channel.POLICY_PATH, _abs_d1d_rule(12, 6), "|d1d|>=12bp", "6-12bp")
_register("DGS1", Channel.POLICY_PATH, _abs_d1d_rule(10, 5), "|d1d|>=10bp", "5-10bp")
_register("DFF", Channel.POLICY_PATH, _dff_rule(), "inter-meeting move OR |d1d|>=27bp+z>=2.0", "drift 2-27bp")
# DFEDTARU: excluded from tiering entirely - see EXCLUDED_FROM_TIERING below
_register("FEDTARMD", Channel.POLICY_PATH, _fedtarmd_rule(), "next-yr median shift>=25bp, no z-gate", "median flat/dispersion shift")
_register("BAA10Y", Channel.CREDIT, _d1d_or_d1w_or_level_rule(8, 20, 2.50, 4, 8, 2.00, 2.50), "|d1d|>=8bp or |d1w|>=20bp or level>=2.50", "d1d 4-8bp or level 2.00-2.50")
_register("NFCI", Channel.CREDIT, _level_cross_or_d4w_rule(0.0, 0.15, 0.07, 0.15, -0.20, 0.0), "level crosses above 0 or d4w>=+0.15", "d4w +0.07-0.15 or level -0.20-0")
_register("ANFCI", Channel.CREDIT, _level_or_d4w_rule(0.25, 0.46, 0.0, 0.25, 0.10, 0.46), "level>=+0.25 or d4w>=+0.46", "level 0-0.25 or d4w +0.10-0.46")
_register("NFCICREDIT", Channel.CREDIT, _level_or_d4w_rule(0.25, 0.20, 0.0, 0.25, 0.10, 0.20), "level>=+0.25 or d4w>=+0.20", "d4w +0.10-0.20")
_register("DRTSCILM", Channel.CREDIT, _level_or_dq_rule(20, 19, 5, 20, 7, 19), "level>=+20 or dq>=+19pp", "level +5-20 or dq +7-19pp")
_register("WALCL", Channel.LIQUIDITY, _abs_d4w_rule(100, 40, 100), "|d4w|>=$100bn", "$40-100bn")
_register("RRPONTSYD", Channel.LIQUIDITY, _abs_d4w_rule(150, 75, 150), "|d1w|>=$150bn (excl month/quarter-end)", "$75-150bn")
_register("WTREGEN", Channel.LIQUIDITY, _abs_d4w_rule(150, 75, 150), "|d4w|>=$150bn (outside tax weeks)", "$75-150bn")
_register("WRESBAL", Channel.LIQUIDITY, _abs_d4w_rule(150, 60, 150), "|d4w|>=$150bn or bottom decile 2yr range", "$60-150bn")
_register("TOTRESNS", Channel.LIQUIDITY, _abs_pct_rule("d3m_pct", 13, 2, 13), "|d3m|>=13% of level", "2-13%")
_register("DTWEXBGS", Channel.CURRENCY, _dtwexbgs_rule(), "|d1d|>=0.75% or |d4w|>=2.5%", "d1d 0.35-0.75%")

# --- Early-arriving hard data (5) ---
_register("ICSA", Channel.REAL_ECONOMY, _abs_pct_rule("d4w_pct", 24, 5, 24), "4wk MA>=24% above trailing 12mo low", "4wk MA 5-24% above low")
_register("WEI", Channel.REAL_ECONOMY, _abs_pct_rule("d4w_bp", 1.11, 0.35, 1.11), "|d4w|>=1.11pp or level crosses 0", "|d4w| 0.35-1.11pp")
_register("GACDFSA066MSFRBPHI", Channel.REAL_ECONOMY, _abs_pct_rule("dm_pp", 20, 12, 20), "|dm|>=20pts or 3mo MA crosses zero", "|dm| 12-20pts")
_register("NEWORDER", Channel.REAL_ECONOMY, _abs_pct_rule("dm_pp", 5.2, 1.0, 5.2), "|dm/m|>=5.2% or 3mo annualised beyond +-8%", "|dm/m| 1.0-5.2%")
_register("close_today_bal", Channel.LIQUIDITY, _abs_pct_rule("d4w_bp", 271, 100, 271), "never alone; net liquidity |d4w|>=$271bn", "net liquidity |d4w| $100-271bn")

# --- Consumer and market-facing (17) ---
_register("CPIAUCSL", Channel.POLICY_PATH, _abs_pct_rule("dm_vs_trailing_pp", 0.45, 0.08, 0.45), "|m/m-trailing12m avg|>=0.45pp", "0.08-0.45pp")
_register("CPILFESL", Channel.POLICY_PATH, _abs_pct_rule("dm_vs_trailing_pp", 0.15, 0.08, 0.15), "|m/m-trailing12m avg|>=0.15pp", "0.08-0.15pp")
_register("PCEPILFE", Channel.POLICY_PATH, _abs_pct_rule("dm_vs_trailing_pp", 0.65, 0.08, 0.65), "|m/m-trailing12m avg|>=0.65pp", "0.08-0.65pp")
_register("PAYEMS", Channel.REAL_ECONOMY, _payems_rule(), "|dm-trailing12m avg|>=347k or net revision>=+-100k", "50-347k")
_register("UNRATE", Channel.REAL_ECONOMY, _unrate_rule(), "dm>=+0.3pp", "+-0.1pp with 3mo trend agreeing")
_register("SAHMREALTIME", Channel.REAL_ECONOMY, _sahm_rule(), "crosses>=0.50", "0.30-0.50")
_register("JTSJOL", Channel.REAL_ECONOMY, _abs_pct_rule("d3m_pct", 11, 2, 11), "|d3m|>=11% of level", "2-11%")
_register("CCSA", Channel.REAL_ECONOMY, _abs_pct_rule("d4w_pct", 25, 2, 25), "4wk MA>=25% above trailing 12mo low", "2-25%")
_register("RSAFS", Channel.REAL_ECONOMY, _abs_pct_rule("dm_pp", 1.87, 0.5, 1.87), "|dm/m|>=1.87%", "0.5-1.87%")
_register("HOUST", Channel.REAL_ECONOMY, _hous_style_rule(8, 15, 8, 15), "|d 3mo avg|>=8% or single month|d|>=15%", "single month 8-15%")
_register("PERMIT", Channel.REAL_ECONOMY, _hous_style_rule(5, 9.4, 3, 9.4), "|dm/m|>=9.4% or 3mo avg turning>=5%", "3-9.4%")
_register("MORTGAGE30US", Channel.DISCOUNT_RATE, _d1d_or_d1w_or_level_rule(999999, 20, 999999, 10, 20, -1, -1), "|d1w|>=20bp or |d4w|>=40bp", "10-20bp")
_register("CSUSHPINSA", Channel.REAL_ECONOMY, _csushpinsa_rule(), "y/y crosses zero or |d3m annualised-trailing|>=10pp", "2-10pp")
_register("TOTALSL", Channel.CREDIT, _abs_pct_rule("d4w_bp", 12.32, 1.5, 12.32), "|annualised growth-trailing12m avg|>=12.32pp", "1.5-12.32pp")
_register("DRCCLACBS", Channel.CREDIT, _drcclacbs_rule(), "dq>=+0.25pp or level>=3.5%", "dq +0.10-0.25pp")
_register("VIXCLS", Channel.RISK_APPETITE, _vix_rule(), "(d1d>=+20% or level>=30) AND z>=2.0", "(d1d +10-20% or level 20-30) AND z>=1.0")
_register("VXVCLS", Channel.RISK_APPETITE, _vxv_ratio_rule(), "(ratio>=1.00) AND z>=2.0 on ratio", "ratio 0.95-1.00 AND z>=1.0")

EXCLUDED_FROM_TIERING: frozenset[str] = frozenset({"DFEDTARU"})

CHANNEL_MEMBERS: dict[Channel, list[str]] = {
    Channel.POLICY_PATH: ["DGS3MO", "DGS1", "DGS2", "DFF", "DFEDTARU", "FEDTARMD", "CPIAUCSL", "CPILFESL", "PCEPILFE"],
    Channel.DISCOUNT_RATE: ["DFII10", "DFII5", "T10YIE", "T5YIFR", "DGS10", "T10Y2Y", "T10Y3M", "MORTGAGE30US"],
    Channel.CREDIT: ["BAA10Y", "NFCI", "ANFCI", "NFCICREDIT", "DRTSCILM", "TOTALSL", "DRCCLACBS"],
    Channel.LIQUIDITY: ["WALCL", "RRPONTSYD", "WTREGEN", "WRESBAL", "TOTRESNS", "close_today_bal"],
    Channel.REAL_ECONOMY: ["ICSA", "CCSA", "WEI", "GACDFSA066MSFRBPHI", "NEWORDER", "PAYEMS", "UNRATE", "SAHMREALTIME", "JTSJOL", "RSAFS", "HOUST", "PERMIT", "CSUSHPINSA"],
    Channel.CURRENCY: ["DTWEXBGS"],
    Channel.RISK_APPETITE: ["VIXCLS", "VXVCLS"],
}


def tier_series_move(move: SeriesMove) -> TierResult:
    if move.series_id in EXCLUDED_FROM_TIERING:
        raise ValueError(f"{move.series_id} is excluded from tiering - route to the context-field path instead.")
    rule = THRESHOLDS.get(move.series_id)
    if rule is None:
        raise KeyError(f"No threshold rule registered for series_id={move.series_id!r}")
    return rule.evaluate(move)
