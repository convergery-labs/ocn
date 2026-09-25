"""Tests for the full Macro Signal Backbone pipeline (signal-detection-agent
side): Z-SCORE -> TIER -> SUPPRESS -> COLLAPSE -> INTERPRET, plus storage,
the FOMC calendar, confirmation reversal (mechanism C), and the HTTP
trigger chain.

Merged from 12 separate per-module test files into one, at the user's
explicit request - each section below still maps 1:1 to the source module
it tests, same coverage as before, just consolidated into a single file.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'src'))

from models.jobs import insert_macro_signal_event
from pipeline.macro_signal_collapse import collapse_events
from pipeline.macro_signal_confirmation import check_confirmation_reversal
from pipeline.macro_signal_fedtarmd import compute_sep_median_shift_bp
from pipeline.macro_signal_fomc_calendar import (
    calendar_staleness_warning,
    fetch_fomc_meeting_dates,
    is_scheduled_fomc_date,
    is_within_known_calendar_horizon,
    refresh_fomc_meeting_dates,
)
from pipeline.macro_signal_interpret import (
    InterpretationValidationError,
    load_system_prompt,
    validate_interpretation,
)
from pipeline.macro_signal_suppress import (
    SuppressibleResult,
    apply_collinear_suppression,
    apply_derived_suppression,
)
from pipeline.macro_signal_thresholds import (
    CHANNEL_MEMBERS,
    EXCLUDED_FROM_TIERING,
    THRESHOLDS,
    SeriesMove,
    Tier,
    tier_series_move,
)
from pipeline.macro_signal_zscore import (
    compute_daily_changes,
    compute_series_zscores,
    rolling_zscore,
)


# ============================================================================
# Z-SCORE  (from test_macro_signal_zscore.py)
# ============================================================================

def test_compute_daily_changes_native_bp():
    obs = [
        {"observation_date": date(2026, 1, 1), "value": 4.00},
        {"observation_date": date(2026, 1, 2), "value": 4.05},
    ]
    changes = compute_daily_changes(obs)
    assert changes[date(2026, 1, 2)] == pytest.approx(5.0)  # 0.05 pct -> 5bp


def test_compute_daily_changes_is_exact_not_float_imprecise():
    """Regression test for a real bug found live (frontend ticket after
    job 262, 2026-09-25): float(value) then float subtraction (e.g.
    0.31 - 0.26) picks up binary-float imprecision - the real move here
    is exactly 5bp, but float arithmetic can yield 4.999999999999996 or
    5.000000000000004 depending on the exact inputs. A truncation step
    added to "clean up" the noise made it WORSE (49.99999999999996
    truncates to 49.99, not the real 50). The real fix is Decimal(str(
    value)) arithmetic - exact, not approximate - so this test asserts
    exact equality (==), not pytest.approx, on several of the exact real
    values the frontend reported as wrong (5, 13, -8, 9)."""
    cases = [
        (0.26, 0.31, 5.0),
        (0.80, 0.93, 13.0),
        (4.53, 4.45, -8.0),
        (2.10, 2.19, 9.0),
    ]
    for prior, current, expected_bp in cases:
        obs = [
            {"observation_date": date(2026, 1, 1), "value": prior},
            {"observation_date": date(2026, 1, 2), "value": current},
        ]
        changes = compute_daily_changes(obs)
        assert changes[date(2026, 1, 2)] == expected_bp, (
            f"{prior} -> {current}: expected exactly {expected_bp}bp, got {changes[date(2026, 1, 2)]}"
        )


def test_compute_daily_changes_skips_null_values():
    obs = [
        {"observation_date": date(2026, 1, 1), "value": 4.00},
        {"observation_date": date(2026, 1, 2), "value": None},
        {"observation_date": date(2026, 1, 3), "value": 4.10},
    ]
    changes = compute_daily_changes(obs)
    # Only 2 real observations remain (Jan 1, Jan 3) -> one change between them
    assert len(changes) == 1
    assert changes[date(2026, 1, 3)] == pytest.approx(10.0)


def test_rolling_zscore_requires_minimum_sample():
    # Fewer than 30 changes in the window -> no z-score computed
    base = date(2026, 1, 1)
    changes = {base + timedelta(days=i): 1.0 for i in range(10)}
    z = rolling_zscore(changes, window_days=730)
    assert z == {}


def test_rolling_zscore_computes_with_sufficient_sample():
    base = date(2026, 1, 1)
    # 40 days of small noise, then a large outlier on day 41
    changes = {base + timedelta(days=i): (0.5 if i % 2 == 0 else -0.5) for i in range(40)}
    changes[base + timedelta(days=40)] = 20.0
    z = rolling_zscore(changes, window_days=730)
    assert (base + timedelta(days=40)) in z
    assert z[base + timedelta(days=40)] > 2.0  # a real outlier relative to +-0.5 noise


def test_compute_series_zscores_end_to_end():
    base = date(2024, 1, 1)
    obs = []
    value = 4.0
    for i in range(400):
        obs.append({"observation_date": base + timedelta(days=i), "value": value})
        value += 0.001 if i % 3 else -0.001
    result = compute_series_zscores(obs, window_days=365)
    assert len(result) > 0
    for d, (change, z) in result.items():
        assert isinstance(change, float)
        assert isinstance(z, float)

# ============================================================================
# TIER (thresholds)  (from test_macro_signal_thresholds.py)
# ============================================================================

def test_all_46_series_registered_exactly_once():
    total = len(THRESHOLDS) + len(EXCLUDED_FROM_TIERING)
    assert total == 46
    assert THRESHOLDS.keys().isdisjoint(EXCLUDED_FROM_TIERING)


def test_channel_membership_matches_registered_series_exactly():
    channel_all = set()
    for members in CHANNEL_MEMBERS.values():
        for m in members:
            assert m not in channel_all, f"{m} listed in multiple channels"
            channel_all.add(m)
    registered_all = set(THRESHOLDS.keys()) | EXCLUDED_FROM_TIERING
    assert channel_all == registered_all


def test_dfii5_high_at_spec_worked_example_numbers():
    # Real numbers from Step 0's live FRED validation on 2026-08-28.
    r = tier_series_move(SeriesMove("DFII5", d1d_bp=11.0, z=2.472))
    assert r.tier == Tier.HIGH


def test_dgs1_high_at_spec_worked_example_numbers():
    r = tier_series_move(SeriesMove("DGS1", d1d_bp=11.0, z=2.943))
    assert r.tier == Tier.HIGH


def test_weak_band_requires_both_floor_and_z():
    r = tier_series_move(SeriesMove("DFII10", d1d_bp=6.0, z=1.5))
    assert r.tier == Tier.WEAK


def test_noise_below_floor_even_with_high_z():
    r = tier_series_move(SeriesMove("DFII10", d1d_bp=3.0, z=2.5))
    assert r.tier == Tier.NOISE


def test_sign_flip_rule_high_without_floor():
    r = tier_series_move(SeriesMove("T10Y2Y", d1d_bp=2.0, sign_flip=True, z=2.5))
    assert r.tier == Tier.HIGH


def test_sign_flip_rule_high_via_floor_alone():
    r = tier_series_move(SeriesMove("T10Y2Y", d1d_bp=9.0, sign_flip=False, z=2.5))
    assert r.tier == Tier.HIGH


def test_compound_d1d_or_d1w_or_level_rule_via_d1w():
    r = tier_series_move(SeriesMove("BAA10Y", d1d_bp=2.0, d1w_bp=25.0, level=1.0, z=2.5))
    assert r.tier == Tier.HIGH


def test_compound_d1d_or_d1w_or_level_rule_via_level():
    r = tier_series_move(SeriesMove("BAA10Y", d1d_bp=1.0, d1w_bp=1.0, level=2.60, z=2.5))
    assert r.tier == Tier.HIGH


def test_level_crossing_rule_nfci():
    r = tier_series_move(SeriesMove("NFCI", prior_level=-0.05, level=0.10, d4w_bp=0.05, z=2.5))
    assert r.tier == Tier.HIGH


def test_level_crossing_rule_no_cross_no_event():
    r = tier_series_move(SeriesMove("NFCI", prior_level=-0.30, level=-0.25, d4w_bp=0.05, z=2.5))
    assert r.tier == Tier.NOISE


def test_payems_high_via_revision_alone():
    r = tier_series_move(SeriesMove("PAYEMS", dm_vs_trailing_pp=100.0, net_revision_k=150.0, z=2.5))
    assert r.tier == Tier.HIGH


def test_payems_high_via_deviation_alone():
    r = tier_series_move(SeriesMove("PAYEMS", dm_vs_trailing_pp=400.0, net_revision_k=0.0, z=2.5))
    assert r.tier == Tier.HIGH


def test_unrate_signed_rule_rise_is_high():
    r = tier_series_move(SeriesMove("UNRATE", dm_pp=0.4, z=2.5))
    assert r.tier == Tier.HIGH


def test_unrate_signed_rule_fall_is_not_high():
    r = tier_series_move(SeriesMove("UNRATE", dm_pp=-0.4, z=2.5))
    assert r.tier != Tier.HIGH


def test_vix_asymmetric_spike_is_high():
    r = tier_series_move(SeriesMove("VIXCLS", d1d_bp=25.0, level=22.0, z=2.5))
    assert r.tier == Tier.HIGH


def test_vix_asymmetric_drop_is_not_high():
    r = tier_series_move(SeriesMove("VIXCLS", d1d_bp=-25.0, level=22.0, z=2.5))
    assert r.tier != Tier.HIGH


def test_vxv_ratio_inversion_is_high():
    r = tier_series_move(SeriesMove("VXVCLS", ratio=1.05, z=2.5))
    assert r.tier == Tier.HIGH


def test_vxv_ratio_no_inversion_is_noise():
    r = tier_series_move(SeriesMove("VXVCLS", ratio=0.80, z=2.5))
    assert r.tier == Tier.NOISE


def test_dff_inter_meeting_move_high_with_no_gate():
    r = tier_series_move(SeriesMove("DFF", is_inter_meeting_date=True, d1d_bp=1.0, z=0.1))
    assert r.tier == Tier.HIGH


def test_dff_scheduled_date_high_via_size_and_z():
    r = tier_series_move(SeriesMove("DFF", is_inter_meeting_date=False, d1d_bp=30.0, z=2.5))
    assert r.tier == Tier.HIGH


def test_dff_scheduled_date_size_alone_not_high():
    r = tier_series_move(SeriesMove("DFF", is_inter_meeting_date=False, d1d_bp=30.0, z=1.0))
    assert r.tier != Tier.HIGH


def test_dff_ordinary_drift_is_weak():
    r = tier_series_move(SeriesMove("DFF", is_inter_meeting_date=False, d1d_bp=10.0, z=0.1))
    assert r.tier == Tier.WEAK


def test_fedtarmd_high_with_no_z_gate():
    r = tier_series_move(SeriesMove("FEDTARMD", sep_median_shift_bp=30.0, z=None))
    assert r.tier == Tier.HIGH


def test_fedtarmd_weak_below_threshold():
    r = tier_series_move(SeriesMove("FEDTARMD", sep_median_shift_bp=10.0, z=None))
    assert r.tier == Tier.WEAK


def test_dfedtaru_raises_when_tiered_directly():
    with pytest.raises(ValueError):
        tier_series_move(SeriesMove("DFEDTARU", d1d_bp=25.0, z=5.0))


def test_every_registered_series_handles_missing_data_gracefully():
    for series_id, rule in THRESHOLDS.items():
        result = rule.evaluate(SeriesMove(series_id))
        assert result.tier == Tier.NOISE, f"{series_id} should be NOISE on empty data, got {result.tier}"


# ============================================================================
# plain_reason (real ask: frontend ticket, 2026-09-25 - classification_reason)
# ============================================================================
# Cross-checks the exact worked examples the frontend gave in their own
# message, so a real regression here (a rule's sentence silently drifting
# from what actually fired) is caught immediately, not just "some sentence
# exists".

def test_plain_reason_dfii10_high_names_tier_and_threshold():
    r = THRESHOLDS["DFII10"].evaluate(SeriesMove("DFII10", d1d_bp=13.0, z=2.61))
    assert r.tier == Tier.HIGH
    assert r.plain_reason == "1-day move of 13bp cleared the 10bp HIGH floor (z = +2.61)."


def test_plain_reason_t10y2y_weak_names_tier_and_threshold():
    r = THRESHOLDS["T10Y2Y"].evaluate(SeriesMove("T10Y2Y", d1d_bp=5.0, z=1.54, sign_flip=False))
    assert r.tier == Tier.WEAK
    assert r.plain_reason == "1-day move of 5bp cleared the 4bp WEAK floor (z = +1.54)."


def test_plain_reason_t10y3m_high_names_tier_and_threshold():
    r = THRESHOLDS["T10Y3M"].evaluate(SeriesMove("T10Y3M", d1d_bp=12.0, z=2.51, sign_flip=False))
    assert r.tier == Tier.HIGH
    assert r.plain_reason == "1-day move of 12bp cleared the 10bp HIGH floor (z = +2.51)."


def test_plain_reason_baa10y_weak_band_names_the_band_generically():
    r = THRESHOLDS["BAA10Y"].evaluate(SeriesMove("BAA10Y", d1d_bp=6.0, z=-1.67))
    assert r.tier == Tier.WEAK
    assert r.plain_reason == "Move fell in this series' WEAK band (z = -1.67)."


def test_plain_reason_dff_weak_drift_says_no_zscore_check():
    r = THRESHOLDS["DFF"].evaluate(SeriesMove("DFF", is_inter_meeting_date=False, d1d_bp=25.0, z=0.1))
    assert r.tier == Tier.WEAK
    assert r.plain_reason == "1-day move of 25bp was within the 2-27bp WEAK range (no z-score check)."


def test_plain_reason_dff_inter_meeting_names_no_gate_explicitly():
    r = THRESHOLDS["DFF"].evaluate(SeriesMove("DFF", is_inter_meeting_date=True, d1d_bp=0.0, z=0.0))
    assert r.tier == Tier.HIGH
    assert "inter-meeting move" in r.plain_reason.lower()
    assert "no size or z-score check" in r.plain_reason.lower()


def test_plain_reason_t10y2y_sign_flip_names_it_explicitly():
    """Real ask: sign flips must say so explicitly, e.g. "The spread
    crossed zero (curve un-inverted)..." - distinct wording from the
    plain bp-threshold branch, even though both are the HIGH gate."""
    r = THRESHOLDS["T10Y2Y"].evaluate(SeriesMove("T10Y2Y", d1d_bp=1.0, z=2.1, sign_flip=True))
    assert r.tier == Tier.HIGH
    assert "crossed zero" in r.plain_reason.lower()
    assert "curve un-inverted" in r.plain_reason.lower()
    assert "z = +2.10" in r.plain_reason


def test_plain_reason_fedtarmd_high_matches_ticket_example():
    """Exact worked example from the frontend's own message: "The 2027
    SEP median moved 50bp, above the 25bp HIGH threshold (no z-score
    check).\""""
    r = THRESHOLDS["FEDTARMD"].evaluate(SeriesMove("FEDTARMD", sep_median_shift_bp=50.0, z=None))
    assert r.tier == Tier.HIGH
    assert r.plain_reason == "The SEP median moved 50bp, above the 25bp HIGH threshold (no z-score check)."


def test_plain_reason_is_none_on_noise_and_missing_data():
    """Real ask: "If an event doesn't have the field, the page keeps
    today's z-score sentence" - implies plain_reason is genuinely absent
    (None), not an empty string, for NOISE/missing-data results, which
    never reach INTERPRET anyway (see macro_signal_collapse.py) but
    should still be well-formed if ever inspected directly."""
    r = THRESHOLDS["DFII10"].evaluate(SeriesMove("DFII10"))
    assert r.tier == Tier.NOISE
    assert r.plain_reason is None

    r2 = THRESHOLDS["DFII10"].evaluate(SeriesMove("DFII10", d1d_bp=1.0, z=0.1))
    assert r2.tier == Tier.NOISE
    assert r2.plain_reason is None


def test_plain_reason_every_high_or_weak_result_has_one():
    """Every registered series' rule must produce a plain_reason on both
    its HIGH and WEAK branches - a systematic check across all 46
    series, not just the ones spot-checked above, so a future rule
    addition that forgets plain_reason fails loudly here instead of
    silently shipping a null classification_reason."""
    import inspect
    for series_id, rule in THRESHOLDS.items():
        # A move large enough to plausibly clear most series' HIGH floors,
        # with a big z-score - not guaranteed to hit HIGH for every shape
        # (e.g. VIXCLS needs specific signed d1d), so this only asserts
        # when a HIGH/WEAK result actually comes back, not that one always
        # does for this synthetic input.
        move = SeriesMove(
            series_id, d1d_bp=500.0, d1w_bp=500.0, d4w_bp=500.0, d4w_pct=50.0,
            d3m_pct=50.0, dm_pp=50.0, dm_vs_trailing_pp=500.0, dq_pp=50.0,
            level=500.0, prior_level=-500.0, z=10.0, net_revision_k=500.0,
            sign_flip=True, is_inter_meeting_date=False, sep_median_shift_bp=500.0,
            ratio=10.0, ratio_d1d_pct=500.0,
        )
        result = rule.evaluate(move)
        if result.tier in (Tier.HIGH, Tier.WEAK):
            assert result.plain_reason is not None, f"{series_id} tiered {result.tier} with no plain_reason"
            assert result.tier.value in result.plain_reason.upper(), (
                f"{series_id}'s plain_reason doesn't literally name its tier ({result.tier.value}): {result.plain_reason!r}"
            )

# ============================================================================
# SUPPRESS (mechanisms A & B)  (from test_macro_signal_suppress.py)
# ============================================================================

def mk_suppress(series_id, tier, z=2.5):
    return SuppressibleResult(series_id, tier, z, "test")


def test_dgs10_suppressed_when_either_leg_fired():
    results = {
        "DGS10": mk_suppress("DGS10", Tier.HIGH),
        "DFII10": mk_suppress("DFII10", Tier.HIGH),
        "T10YIE": mk_suppress("T10YIE", Tier.NOISE),
    }
    apply_derived_suppression(results)
    assert results["DGS10"].suppressed_by == "derived:DFII10+T10YIE"


def test_dgs10_not_suppressed_when_neither_leg_fired():
    results = {
        "DGS10": mk_suppress("DGS10", Tier.HIGH),
        "DFII10": mk_suppress("DFII10", Tier.NOISE),
        "T10YIE": mk_suppress("T10YIE", Tier.NOISE),
    }
    apply_derived_suppression(results)
    assert results["DGS10"].suppressed_by is None


def test_t10y2y_requires_both_legs_fired():
    results = {
        "T10Y2Y": mk_suppress("T10Y2Y", Tier.HIGH),
        "DGS10": mk_suppress("DGS10", Tier.HIGH),
        "DGS2": mk_suppress("DGS2", Tier.NOISE),
    }
    apply_derived_suppression(results)
    assert results["T10Y2Y"].suppressed_by is None

    results["DGS2"] = mk_suppress("DGS2", Tier.WEAK)
    apply_derived_suppression(results)
    assert results["T10Y2Y"].suppressed_by == "derived:DGS10+DGS2"


def test_t10y3m_requires_both_legs_fired():
    results = {
        "T10Y3M": mk_suppress("T10Y3M", Tier.HIGH),
        "DGS10": mk_suppress("DGS10", Tier.HIGH),
        "DGS3MO": mk_suppress("DGS3MO", Tier.HIGH),
    }
    apply_derived_suppression(results)
    assert results["T10Y3M"].suppressed_by == "derived:DGS10+DGS3MO"


def test_pcepilfe_suppressed_when_cpilfesl_fired():
    results = {
        "PCEPILFE": mk_suppress("PCEPILFE", Tier.HIGH),
        "CPILFESL": mk_suppress("CPILFESL", Tier.HIGH),
    }
    apply_derived_suppression(results)
    assert results["PCEPILFE"].suppressed_by == "derived:CPILFESL"


def test_collinear_cluster_keeps_high_highest_z_suppresses_rest():
    results = {
        "DGS3MO": mk_suppress("DGS3MO", Tier.WEAK, z=1.5),
        "DGS1": mk_suppress("DGS1", Tier.HIGH, z=2.9),
        "DGS2": mk_suppress("DGS2", Tier.WEAK, z=1.8),
    }
    apply_collinear_suppression(results)
    assert results["DGS3MO"].suppressed_by == "collinear:DGS1"
    assert results["DGS2"].suppressed_by == "collinear:DGS1"
    assert results["DGS1"].suppressed_by is None


def test_all_weak_cluster_does_not_suppress():
    """Spec's explicit reasoning: two moderate legs must not hide a
    genuinely large move in the spread between them."""
    results = {
        "DGS3MO": mk_suppress("DGS3MO", Tier.WEAK, z=1.2),
        "DGS1": mk_suppress("DGS1", Tier.WEAK, z=1.3),
        "DGS2": mk_suppress("DGS2", Tier.WEAK, z=1.1),
    }
    apply_collinear_suppression(results)
    assert all(r.suppressed_by is None for r in results.values())


def test_cpi_cluster_prefers_core_over_highest_z():
    results = {
        "CPIAUCSL": mk_suppress("CPIAUCSL", Tier.HIGH, z=3.0),
        "CPILFESL": mk_suppress("CPILFESL", Tier.HIGH, z=2.1),
    }
    apply_collinear_suppression(results)
    assert results["CPIAUCSL"].suppressed_by == "collinear:CPILFESL"
    assert results["CPILFESL"].suppressed_by is None


def test_vix_vxv_cluster_keeps_higher_z():
    results = {
        "VIXCLS": mk_suppress("VIXCLS", Tier.HIGH, z=2.8),
        "VXVCLS": mk_suppress("VXVCLS", Tier.WEAK, z=1.5),
    }
    apply_collinear_suppression(results)
    assert results["VXVCLS"].suppressed_by == "collinear:VIXCLS"


def test_single_fired_member_not_suppressed():
    results = {
        "HOUST": mk_suppress("HOUST", Tier.HIGH, z=2.5),
        "PERMIT": mk_suppress("PERMIT", Tier.NOISE, z=0.2),
    }
    apply_collinear_suppression(results)
    assert results["HOUST"].suppressed_by is None

# ============================================================================
# COLLAPSE  (from test_macro_signal_collapse.py)
# ============================================================================

_KT = datetime(2026, 8, 28, 16, 30, tzinfo=timezone.utc)


def mk(series_id, tier=Tier.HIGH, z=2.5, suppressed_by=None):
    return SuppressibleResult(series_id, tier, z, "test", suppressed_by=suppressed_by)


def test_same_release_same_channel_collapses_into_one_event():
    survivors = [mk("DFII10"), mk("T5YIFR")]  # both discount_rate
    release_id_of = {"DFII10": 18, "T5YIFR": 18}
    kt_of = {"DFII10": _KT, "T5YIFR": _KT}
    events = collapse_events(survivors, release_id_of, kt_of)
    assert len(events) == 1
    assert set(events[0].member_ids) == {"DFII10", "T5YIFR"}


def test_same_release_different_channel_does_not_collapse():
    """Known, documented tension with the spec's own worked example
    (DFII5+DGS1 on 2026-08-28) - see collapse.py's module docstring."""
    survivors = [mk("DFII5"), mk("DGS1")]  # discount_rate vs policy_path
    release_id_of = {"DFII5": 18, "DGS1": 18}
    kt_of = {"DFII5": _KT, "DGS1": _KT}
    events = collapse_events(survivors, release_id_of, kt_of)
    assert len(events) == 2
    assert all(len(e.members) == 1 for e in events)


def test_isolated_survivor_is_its_own_event():
    survivors = [mk("VIXCLS")]
    release_id_of = {"VIXCLS": 200}
    kt_of = {"VIXCLS": _KT}
    events = collapse_events(survivors, release_id_of, kt_of)
    assert len(events) == 1
    assert len(events[0].members) == 1


def test_suppressed_rows_excluded_from_collapse():
    survivors = [mk("DFII10"), mk("T5YIFR", suppressed_by="collinear:DFII10")]
    release_id_of = {"DFII10": 18, "T5YIFR": 18}
    kt_of = {"DFII10": _KT, "T5YIFR": _KT}
    events = collapse_events(survivors, release_id_of, kt_of)
    assert len(events) == 1
    assert events[0].member_ids == ["DFII10"]


def test_same_channel_different_release_does_not_collapse():
    survivors = [mk("DFII10"), mk("DFII5")]  # both discount_rate
    release_id_of = {"DFII10": 18, "DFII5": 999}
    kt_of = {"DFII10": _KT, "DFII5": _KT}
    events = collapse_events(survivors, release_id_of, kt_of)
    assert len(events) == 2

# ============================================================================
# Confirmation reversal (mechanism C) - the arithmetic check  (from test_macro_signal_confirmation.py)
# ============================================================================

def test_exact_full_reversal_is_a_reversal():
    """Spec's own example: "Claims rose 28k, reversed the following week"
    -> no event."""
    r = check_confirmation_reversal("ICSA", original_change=28.0, next_change=-28.0)
    assert r.reversed


def test_overshooting_reversal_is_a_reversal():
    r = check_confirmation_reversal("ICSA", original_change=28.0, next_change=-35.0)
    assert r.reversed


def test_partial_reversal_is_not_a_full_reversal():
    r = check_confirmation_reversal("ICSA", original_change=28.0, next_change=-10.0)
    assert not r.reversed


def test_same_sign_continuation_is_not_a_reversal():
    r = check_confirmation_reversal("ICSA", original_change=28.0, next_change=15.0)
    assert not r.reversed


def test_no_next_observation_yet_is_not_reversed():
    r = check_confirmation_reversal("ICSA", original_change=28.0, next_change=None)
    assert not r.reversed
    assert "no_next" in r.reason

# ============================================================================
# Confirmation reversal (mechanism C) - the DB-wired recheck job  (from test_macro_signal_confirmation_recheck.py)
# ============================================================================

def _mock_db():
    mock_conn = MagicMock()
    mock_get_db = MagicMock()
    mock_get_db.return_value.__enter__.return_value = mock_conn
    return mock_conn, mock_get_db


def test_frequency_map_scopes_confirmation_reversal_to_weekly_monthly_only():
    """Mechanism C is spec-scoped to weekly/monthly series only - a
    daily series' 'next observation' is just the following trading day,
    not a meaningful confirmation window."""
    from pipeline.macro_signal_frequency import CONFIRMATION_REVERSAL_ELIGIBLE, Frequency, SERIES_FREQUENCY

    assert len(SERIES_FREQUENCY) == 46
    for series_id in CONFIRMATION_REVERSAL_ELIGIBLE:
        assert SERIES_FREQUENCY[series_id] in (Frequency.WEEKLY, Frequency.MONTHLY)
    # A known daily series must never be eligible
    assert "DGS10" not in CONFIRMATION_REVERSAL_ELIGIBLE
    # A known monthly series must be eligible
    assert "CPIAUCSL" in CONFIRMATION_REVERSAL_ELIGIBLE
    # A known weekly series must be eligible
    assert "ICSA" in CONFIRMATION_REVERSAL_ELIGIBLE
    # Quarterly series are deliberately excluded (spec only names weekly/monthly)
    assert "FEDTARMD" not in CONFIRMATION_REVERSAL_ELIGIBLE
    assert "DRCCLACBS" not in CONFIRMATION_REVERSAL_ELIGIBLE


def test_mark_suppressed_updates_both_signal_detection_and_metadata():
    """CONFIRMED as a real gap before this fix: a confirmation-reversed
    row's metadata.suppressed_by was updated but signal_detection stayed
    'signal'/'weak_signal' - a signal_detection='signal' query would
    still surface an event the pipeline has since determined was not
    real."""
    mock_conn, mock_get_db = _mock_db()
    mock_conn.execute.return_value.rowcount = 1

    with patch("models.jobs.get_db", mock_get_db):
        from models.jobs import mark_macro_signal_event_suppressed
        result = mark_macro_signal_event_suppressed("ICSA-2026-08-28", "confirmation_reversal:ICSA")

    assert result is True
    sql = mock_conn.execute.call_args.args[0]
    assert "signal_detection = 'noise'" in sql
    assert "suppressed_by" in sql


def test_run_confirmation_recheck_suppresses_a_fully_reversed_event():
    """End-to-end: a stored ICSA WEAK event whose next observation fully
    reverses the original move must get marked suppressed."""
    stored_row = {
        "id": 1, "source_id": "ICSA-2026-08-20", "signal_detection": "weak_signal",
        "published": datetime(2026, 8, 20, tzinfo=timezone.utc),
        "metadata": {"tier": "WEAK", "series_id": "ICSA", "suppressed_by": None},
    }
    # Original move: +28k (2026-08-20 vs 2026-08-13). Next observation
    # (2026-08-27) reverses it fully: -30k.
    observations = [
        {"series_id": "ICSA", "observation_date": date(2026, 8, 13), "value": 200.0},
        {"series_id": "ICSA", "observation_date": date(2026, 8, 20), "value": 228.0},
        {"series_id": "ICSA", "observation_date": date(2026, 8, 27), "value": 198.0},
    ]

    with patch("controllers.run.list_macro_signal_events_for_confirmation_recheck", return_value=[stored_row]), \
         patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=observations)), \
         patch("controllers.run.mark_macro_signal_event_suppressed") as mock_mark, \
         patch("controllers.run.update_job_status"):
        mock_mark.return_value = True
        from controllers.run import run_macro_signal_confirmation_recheck
        asyncio.run(run_macro_signal_confirmation_recheck(job_id=1, since_date="2026-08-01"))

    mock_mark.assert_called_once()
    call_args = mock_mark.call_args.args
    assert call_args[0] == "ICSA-2026-08-20"
    assert "confirmation_reversal" in call_args[1]
    assert "ICSA" in call_args[1]


def test_run_confirmation_recheck_does_not_suppress_partial_reversal():
    """A next observation that only partially retraces the original
    move must NOT be suppressed - only a genuine full round-trip does."""
    stored_row = {
        "id": 1, "source_id": "ICSA-2026-08-20", "signal_detection": "weak_signal",
        "published": datetime(2026, 8, 20, tzinfo=timezone.utc),
        "metadata": {"tier": "WEAK", "series_id": "ICSA", "suppressed_by": None},
    }
    observations = [
        {"series_id": "ICSA", "observation_date": date(2026, 8, 13), "value": 200.0},
        {"series_id": "ICSA", "observation_date": date(2026, 8, 20), "value": 228.0},  # +28k
        {"series_id": "ICSA", "observation_date": date(2026, 8, 27), "value": 218.0},  # -10k, partial only
    ]

    with patch("controllers.run.list_macro_signal_events_for_confirmation_recheck", return_value=[stored_row]), \
         patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=observations)), \
         patch("controllers.run.mark_macro_signal_event_suppressed") as mock_mark, \
         patch("controllers.run.update_job_status"):
        from controllers.run import run_macro_signal_confirmation_recheck
        asyncio.run(run_macro_signal_confirmation_recheck(job_id=1, since_date="2026-08-01"))

    mock_mark.assert_not_called()


def test_run_confirmation_recheck_no_op_when_no_next_observation_yet():
    """A row whose next observation hasn't been published yet must be
    left alone, not treated as reversed - check_confirmation_reversal's
    own next_change=None -> not-reversed behavior."""
    stored_row = {
        "id": 1, "source_id": "ICSA-2026-08-20", "signal_detection": "weak_signal",
        "published": datetime(2026, 8, 20, tzinfo=timezone.utc),
        "metadata": {"tier": "WEAK", "series_id": "ICSA", "suppressed_by": None},
    }
    observations = [
        {"series_id": "ICSA", "observation_date": date(2026, 8, 13), "value": 200.0},
        {"series_id": "ICSA", "observation_date": date(2026, 8, 20), "value": 228.0},
        # no 2026-08-27 observation yet
    ]

    with patch("controllers.run.list_macro_signal_events_for_confirmation_recheck", return_value=[stored_row]), \
         patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=observations)), \
         patch("controllers.run.mark_macro_signal_event_suppressed") as mock_mark, \
         patch("controllers.run.update_job_status"):
        from controllers.run import run_macro_signal_confirmation_recheck
        asyncio.run(run_macro_signal_confirmation_recheck(job_id=1, since_date="2026-08-01"))

    mock_mark.assert_not_called()


def test_run_confirmation_recheck_skips_ineligible_daily_series():
    """A row whose member_series are all daily (not weekly/monthly) must
    never be checked at all - mechanism C doesn't apply."""
    stored_row = {
        "id": 1, "source_id": "18-2026-08-20", "signal_detection": "signal",
        "published": datetime(2026, 8, 20, tzinfo=timezone.utc),
        "metadata": {"tier": "HIGH", "member_series": ["DGS10", "DFII10"], "suppressed_by": None},
    }
    with patch("controllers.run.list_macro_signal_events_for_confirmation_recheck", return_value=[stored_row]), \
         patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=[])), \
         patch("controllers.run.mark_macro_signal_event_suppressed") as mock_mark, \
         patch("controllers.run.update_job_status"):
        from controllers.run import run_macro_signal_confirmation_recheck
        asyncio.run(run_macro_signal_confirmation_recheck(job_id=1, since_date="2026-08-01"))

    mock_mark.assert_not_called()


def test_run_confirmation_recheck_no_candidates_completes_cleanly():
    with patch("controllers.run.list_macro_signal_events_for_confirmation_recheck", return_value=[]), \
         patch("controllers.run.update_job_status") as mock_status:
        from controllers.run import run_macro_signal_confirmation_recheck
        asyncio.run(run_macro_signal_confirmation_recheck(job_id=1, since_date="2026-08-01"))

    mock_status.assert_any_call(1, "completed", article_count=0, set_completed_at=True)

# ============================================================================
# FEDTARMD SEP median shift  (from test_macro_signal_fedtarmd.py)
# ============================================================================

_REAL_SNAPSHOTS = {
    date(2025, 6, 18): {2025: 3.9, 2026: 3.6, 2027: 3.4},
    date(2025, 9, 17): {2025: 3.6, 2026: 3.4, 2027: 3.1, 2028: 3.1},
    date(2026, 3, 18): {2026: 3.4, 2027: 3.1, 2028: 3.1},
    date(2026, 6, 17): {2026: 3.8, 2027: 3.6, 2028: 3.4},
    date(2026, 9, 16): {2026: 4.1, 2027: 4.1, 2028: 3.9, 2029: 3.6},
}


def _observations_from_snapshots(snapshots: dict[date, dict[int, float]]) -> list[dict]:
    """value is stored as a string, matching real production shape -
    news-retrieval's macro_observations.value is a Postgres numeric
    column, which /macro/observations serializes as a string (e.g.
    "4.1", not 4.1) - CONFIRMED LIVE. A test fixture passing a bare
    float here would not catch a real type mismatch downstream (see
    the current_values/prior_values string-consistency fix)."""
    rows = []
    for vintage, by_year in snapshots.items():
        for year, value in by_year.items():
            rows.append({
                "series_id": "FEDTARMD",
                "observation_date": date(year, 1, 1),
                "value": str(value),
                "vintage": vintage,
            })
    return rows


def test_real_shift_2026_09_vs_2026_06_matches_hand_computed_value():
    """2026-06-17's 2027 dot: 3.6. 2026-09-16's 2027 dot: 4.1.
    Shift = +0.5pp = +50bp - a real HIGH-tier event (>=25bp).

    Asserts EXACT equality (==), not a tolerance - real bug found live
    (frontend ticket after job 262, 2026-09-25): float arithmetic here
    produced 49.99999999999996 for this exact case, and this test's own
    prior tolerance-based check (abs(x - 50.0) < 1e-6) would have passed
    even with that float-imprecise value, hiding the real bug. Decimal
    arithmetic in macro_signal_fedtarmd.py fixes it - shift_bp is exact."""
    obs = _observations_from_snapshots(_REAL_SNAPSHOTS)
    shift = compute_sep_median_shift_bp(obs, date(2026, 9, 16))
    assert shift is not None
    assert shift.shift_bp == 50.0
    assert shift.target_year == 2027
    assert shift.current_value == Decimal("4.1")
    assert shift.prior_value == Decimal("3.6")


def test_real_shift_2025_09_vs_2025_06_matches_hand_computed_value():
    """2025-06-18's 2026 dot: 3.6. 2025-09-17's 2026 dot: 3.4.
    Shift = -0.2pp = -20bp - below the 25bp HIGH floor."""
    obs = _observations_from_snapshots(_REAL_SNAPSHOTS)
    shift = compute_sep_median_shift_bp(obs, date(2025, 9, 17))
    assert shift is not None
    assert abs(shift.shift_bp - (-20.0)) < 1e-6
    assert shift.target_year == 2026


def test_no_shift_computable_without_a_prior_release():
    """The earliest release in the observation set has no prior SEP to
    compare against - must return None, not fabricate a 0.0 shift."""
    obs = _observations_from_snapshots(_REAL_SNAPSHOTS)
    shift = compute_sep_median_shift_bp(obs, date(2025, 6, 18))
    assert shift is None


def test_none_when_release_date_not_present():
    obs = _observations_from_snapshots(_REAL_SNAPSHOTS)
    shift = compute_sep_median_shift_bp(obs, date(2099, 1, 1))
    assert shift is None


def test_picks_nearest_common_year_when_release_plus_one_missing():
    """A synthetic gap case: release_date.year+1 isn't in the current
    release's own projections (shouldn't happen live, but must degrade
    to the nearest common year rather than crash or silently return
    None when a real comparison IS possible)."""
    snapshots = {
        date(2025, 3, 1): {2027: 3.0, 2028: 2.9},
        date(2025, 6, 1): {2027: 3.2, 2028: 3.0},  # no 2026 in either - fine, both omit it consistently
    }
    obs = _observations_from_snapshots(snapshots)
    shift = compute_sep_median_shift_bp(obs, date(2025, 6, 1))
    assert shift is not None
    assert abs(shift.shift_bp - 20.0) < 1e-6  # 2027: 3.2 - 3.0 = +0.2pp = +20bp (nearest common year used since 2026 absent)
    assert shift.target_year == 2027


def test_crossing_calendar_year_boundary_does_not_silently_compare_wrong_years():
    """Regression test for the exact bug found live before this module
    existed: comparing "each release's own next year relative to
    itself" would take Dec 2025's next-year (2026) against March
    2026's next-year (2027) - different calendar years, a false
    comparison. The real rule is target_year = PRIOR release's
    year+1 (2025+1=2026 here), evaluated against what the CURRENT
    release says about that same year - this test confirms 2026 (not
    2027) is used, and that both releases' real 2026 values feed the
    shift, not a naive same-offset-from-each-release mismatch."""
    snapshots = {
        date(2025, 12, 10): {2026: 3.5, 2027: 3.2},
        date(2026, 3, 18): {2026: 3.4, 2027: 3.1, 2028: 3.0},
    }
    obs = _observations_from_snapshots(snapshots)
    shift = compute_sep_median_shift_bp(obs, date(2026, 3, 18))
    assert shift is not None
    assert shift.target_year == 2026
    # 2026: 3.4 - 3.5 = -0.1pp = -10bp
    assert abs(shift.shift_bp - (-10.0)) < 1e-6


def test_real_fomc_2026_09_16_event_shift_and_target_year_match_ticket():
    """Regression test for a real frontend ticket (2026-09-25): the
    2026-09-16 FOMC event's stored text said "repriced...by 375bp" -
    a number that matched no real per-year shift and named no target
    year. Real data (news-retrieval, 2026-06-17 vs 2026-09-16 SEP
    releases): 2026 +30bp, 2027 +50bp, 2028 +50bp, 2029 new (no prior).
    The module's own "nearest future year" rule picks 2027 (release_
    date.year+1 = 2026+1), so this is the exact real event the ticket
    asked about, locked in against real numbers."""
    snapshots = {
        date(2026, 6, 17): {2026: 3.8, 2027: 3.6, 2028: 3.4},
        date(2026, 9, 16): {2026: 4.1, 2027: 4.1, 2028: 3.9, 2029: 3.6},
    }
    obs = _observations_from_snapshots(snapshots)
    shift = compute_sep_median_shift_bp(obs, date(2026, 9, 16))
    assert shift is not None
    assert shift.target_year == 2027
    assert shift.shift_bp == 50.0
    assert shift.current_value == Decimal("4.1")
    assert shift.prior_value == Decimal("3.6")
    assert shift.prior_release_date == date(2026, 6, 17)

# ============================================================================
# FOMC calendar (DFF inter-meeting detection)  (from test_macro_signal_fomc_calendar.py)
# ============================================================================

_REAL_DFEDTARU_CHANGE_DATES = [
    date(2024, 9, 19), date(2024, 11, 8), date(2024, 12, 19),
    date(2025, 9, 18), date(2025, 10, 30), date(2025, 12, 11),
    date(2026, 9, 17),
]

# The meeting date one calendar day before each real change date above -
# what should actually be stored in fomc_meeting_dates for these to match.
_REAL_MEETING_DATES = frozenset(d - timedelta(days=1) for d in _REAL_DFEDTARU_CHANGE_DATES)


def _mock_db_with_dates(meeting_dates, refreshed_at=None):
    """Builds a mock get_db() whose .execute(...).fetchall()/.fetchone()
    reflects a fomc_meeting_dates table containing exactly meeting_dates."""
    mock_conn = MagicMock()

    def _execute(sql, params=None):
        result = MagicMock()
        if "MAX(meeting_date)" in sql:
            result.fetchone.return_value = {"d": max(meeting_dates) if meeting_dates else None}
        elif "MAX(refreshed_at)" in sql:
            result.fetchone.return_value = {"t": refreshed_at}
        elif "SELECT meeting_date FROM" in sql:
            result.fetchall.return_value = [{"meeting_date": d} for d in meeting_dates]
        return result

    mock_conn.execute.side_effect = _execute
    mock_get_db = MagicMock()
    mock_get_db.return_value.__enter__.return_value = mock_conn
    mock_get_db.return_value.__exit__.return_value = False
    return mock_get_db


def test_all_real_dfedtaru_change_dates_recognized_as_scheduled():
    """CONFIRMED LIVE: every real Fed rate change since 2024 was
    correctly on a scheduled FOMC date (none of these 7 were actual
    emergency inter-meeting moves) - the +1-day observation-date offset
    must be handled or all 7 would wrongly read as inter-meeting."""
    mock_get_db = _mock_db_with_dates(_REAL_MEETING_DATES)
    with patch("pipeline.macro_signal_fomc_calendar.get_db", mock_get_db):
        for d in _REAL_DFEDTARU_CHANGE_DATES:
            assert is_scheduled_fomc_date(d), f"{d} should be recognized as a scheduled FOMC date"


def test_observation_date_must_be_one_day_after_meeting_date():
    """Direct regression test for the exact bug found live: comparing
    observation_date straight against the meeting-dates set (no offset)
    matched ZERO of the 7 real cases."""
    meeting_date = date(2026, 9, 16)
    mock_get_db = _mock_db_with_dates(frozenset({meeting_date}))
    with patch("pipeline.macro_signal_fomc_calendar.get_db", mock_get_db):
        assert is_scheduled_fomc_date(meeting_date + timedelta(days=1))
        assert not is_scheduled_fomc_date(meeting_date)  # the meeting date itself, unoffset, must NOT match


def test_date_within_horizon():
    horizon = max(_REAL_MEETING_DATES)
    mock_get_db = _mock_db_with_dates(_REAL_MEETING_DATES)
    with patch("pipeline.macro_signal_fomc_calendar.get_db", mock_get_db):
        assert is_within_known_calendar_horizon(horizon)
        assert is_within_known_calendar_horizon(horizon - timedelta(days=1))


def test_date_past_horizon_is_not_within_horizon():
    horizon = max(_REAL_MEETING_DATES)
    mock_get_db = _mock_db_with_dates(_REAL_MEETING_DATES)
    with patch("pipeline.macro_signal_fomc_calendar.get_db", mock_get_db):
        assert not is_within_known_calendar_horizon(horizon + timedelta(days=1))
        assert not is_within_known_calendar_horizon(horizon + timedelta(days=365))


def test_empty_table_treats_everything_as_out_of_horizon_and_not_scheduled():
    """A never-refreshed table must fail closed - no date is known to be
    scheduled, and nothing is within the (nonexistent) known horizon."""
    mock_get_db = _mock_db_with_dates(frozenset())
    with patch("pipeline.macro_signal_fomc_calendar.get_db", mock_get_db):
        assert not is_scheduled_fomc_date(date(2026, 9, 18))
        assert not is_within_known_calendar_horizon(date(2026, 9, 18))


def test_staleness_warning_when_table_empty():
    mock_get_db = _mock_db_with_dates(frozenset())
    with patch("pipeline.macro_signal_fomc_calendar.get_db", mock_get_db):
        warning = calendar_staleness_warning(date(2026, 9, 24))
    assert warning is not None
    assert "empty" in warning


def test_staleness_warning_none_when_recently_refreshed_and_within_horizon():
    horizon = date(2026, 12, 17)
    mock_get_db = _mock_db_with_dates(
        frozenset({horizon}),
        refreshed_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    with patch("pipeline.macro_signal_fomc_calendar.get_db", mock_get_db):
        warning = calendar_staleness_warning(date(2026, 9, 24))
    assert warning is None


def test_staleness_warning_when_refresh_is_old():
    horizon = date(2026, 12, 17)
    mock_get_db = _mock_db_with_dates(
        frozenset({horizon}),
        refreshed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with patch("pipeline.macro_signal_fomc_calendar.get_db", mock_get_db):
        warning = calendar_staleness_warning(date(2026, 9, 24))
    assert warning is not None
    assert "refreshed" in warning


def test_staleness_warning_urgent_when_today_past_horizon():
    horizon = date(2026, 9, 1)
    mock_get_db = _mock_db_with_dates(
        frozenset({horizon}),
        refreshed_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    with patch("pipeline.macro_signal_fomc_calendar.get_db", mock_get_db):
        warning = calendar_staleness_warning(date(2026, 9, 24))
    assert warning is not None
    assert "STALE" in warning


def test_fetch_parses_real_feed_shape_filtering_to_press_conference_only():
    """Real federalreserve.gov/json/calendar.json shape (confirmed live):
    a BOM-prefixed JSON object with an events list, each with title/
    month/days - only 'FOMC Press Conference' titled entries are real
    decision-announcement dates; other titled events (e.g. 'FOMC Meeting'
    on the first day of a 2-day meeting) must be excluded."""
    fake_body = (
        '﻿{"events": ['
        '{"title": "FOMC Meeting", "month": "2026-09", "days": "16"},'
        '{"title": "FOMC Press Conference", "month": "2026-09", "days": "17"},'
        '{"title": "FOMC Press Conference", "month": "2026-12", "days": "9"}'
        ']}'
    )
    mock_resp = MagicMock()
    mock_resp.text = fake_body
    mock_resp.raise_for_status.return_value = None
    with patch("pipeline.macro_signal_fomc_calendar.httpx.get", return_value=mock_resp):
        dates = fetch_fomc_meeting_dates()
    assert dates == [date(2026, 9, 17), date(2026, 12, 9)]


def test_refresh_raises_on_empty_feed_rather_than_wiping_table():
    mock_resp = MagicMock()
    mock_resp.text = '{"events": []}'
    mock_resp.raise_for_status.return_value = None
    with patch("pipeline.macro_signal_fomc_calendar.httpx.get", return_value=mock_resp):
        try:
            refresh_fomc_meeting_dates()
            assert False, "expected ValueError on empty feed"
        except ValueError:
            pass


def test_refresh_upserts_each_fetched_date():
    mock_resp = MagicMock()
    mock_resp.text = (
        '{"events": ['
        '{"title": "FOMC Press Conference", "month": "2026-09", "days": "17"},'
        '{"title": "FOMC Press Conference", "month": "2026-12", "days": "9"}'
        ']}'
    )
    mock_resp.raise_for_status.return_value = None
    mock_conn = MagicMock()
    mock_get_db = MagicMock()
    mock_get_db.return_value.__enter__.return_value = mock_conn
    mock_get_db.return_value.__exit__.return_value = False
    with patch("pipeline.macro_signal_fomc_calendar.httpx.get", return_value=mock_resp), \
         patch("pipeline.macro_signal_fomc_calendar.get_db", mock_get_db):
        count = refresh_fomc_meeting_dates()
    assert count == 2
    assert mock_conn.execute.call_count == 2
    for call in mock_conn.execute.call_args_list:
        assert "ON CONFLICT (meeting_date) DO UPDATE" in call.args[0]

# ============================================================================
# INTERPRET (LLM validation + prompt)  (from test_macro_signal_interpret.py)
# ============================================================================

_VALID = {
    "channel": "policy_path",
    "entry_point": "FOMC Decision",
    "assets": ["treasuries", "real_rates", "credit"],
    "transmission": (
        "1-year Treasury rose 11bp in repricing the expected policy path "
        "higher, raising the discount rate on short-duration obligations."
    ),
    "suspect": False,
    "suspect_reason": None,
}


def test_prompt_file_loads_and_is_substantial():
    prompt = load_system_prompt()
    assert len(prompt) > 1000


@pytest.mark.parametrize("expected_substring", [
    "never classify",  # never-classify framing (Appendix A's core rule)
    "signals that",  # banned commentary-language list
    "investors fear",  # banned commentary-language list
    "cleared that rule's own absolute band",  # corrected WEAK definition
    "Both conditions are required",  # corrected WEAK definition
])
def test_prompt_contains_required_substring(expected_substring):
    normalized = " ".join(load_system_prompt().split())
    assert expected_substring in normalized


def test_prompt_instructs_describing_weak_events_not_narrating_absence_of_high():
    """CONFIRMED LIVE (real 2026-09-11/09-21 pipeline runs): without this
    instruction, a WEAK-tier event with several small/mixed-direction
    member moves and no standout number gets a transmission that
    narrates the tier decision ("No series breached the HIGH
    threshold") instead of describing what actually moved - a real
    violation of Appendix A's "it never classifies" rule that the
    original spec text (which only ever gives HIGH examples) didn't
    guard against."""
    prompt = load_system_prompt()
    normalized = " ".join(prompt.split())
    assert "still gets the same transmission you would write for a HIGH one" in normalized
    assert "No series breached the HIGH threshold" in normalized  # the real bad example, named explicitly as wrong


def test_valid_payload_passes():
    result = validate_interpretation(_VALID, expected_channel="policy_path")
    assert result == _VALID


def test_valid_payload_passes_with_matching_members():
    members = [{"series_id": "DGS1", "value": 4.45, "move_bp": 11.0, "z_score": 1.6, "tier": "WEAK"}]
    result = validate_interpretation(_VALID, expected_channel="policy_path", members=members)
    assert result == _VALID


def test_transmission_bp_number_mismatching_real_move_bp_is_rejected():
    """Regression test for the exact real bug (2026-09-24 audit, T10Y2Y):
    "steepened by 31bp" was accepted for a real +5bp move because
    nothing ever cross-checked the written number against move_bp. This
    is the fix - the same wrong-number sentence must now fail
    validation (member's real move_bp is 5.0, sentence claims 31bp,
    outside the 1bp tolerance)."""
    bad = {**_VALID, "transmission": "The 10y-2y Treasury spread steepened by 31bp, raising the discount rate."}
    members = [{"series_id": "T10Y2Y", "value": 0.31, "move_bp": 5.0, "z_score": 1.5, "tier": "WEAK"}]
    with pytest.raises(InterpretationValidationError, match="numbers don't match"):
        validate_interpretation(bad, expected_channel="policy_path", members=members)


def test_transmission_direction_word_mismatching_move_bp_sign_is_rejected():
    bad = {**_VALID, "transmission": "The 1-year Treasury yield fell 11bp, easing the policy path."}
    members = [{"series_id": "DGS1", "value": 4.45, "move_bp": 11.0, "z_score": 1.6, "tier": "WEAK"}]
    with pytest.raises(InterpretationValidationError, match="numbers don't match"):
        validate_interpretation(bad, expected_channel="policy_path", members=members)


def test_transmission_bp_number_within_tolerance_of_slightly_rounded_move_bp_passes():
    """A sentence may round a real value for readability (e.g. "50bp"
    for a real 49.99, which itself may be an exact value someone chose
    to write with one fewer significant figure, or a genuinely
    non-integer real move) - this must still pass, not be rejected over
    sub-bp difference. move_bp itself is exact as of the Decimal fix in
    macro_signal_zscore.py/macro_signal_fedtarmd.py; this test is about
    the fact-check's own tolerance, independent of that."""
    ok = {**_VALID, "transmission": "The 2027 median dot in the FOMC SEP rose 50bp, raising the expected policy path."}
    members = [{"series_id": "FEDTARMD", "value": 4.1, "move_bp": 49.99, "z_score": None, "tier": "HIGH"}]
    result = validate_interpretation(ok, expected_channel="policy_path", members=members)
    assert result == ok


def test_missing_required_field_raises():
    bad = dict(_VALID)
    del bad["assets"]
    with pytest.raises(InterpretationValidationError):
        validate_interpretation(bad, expected_channel="policy_path")


def test_channel_unclear_is_also_force_corrected():
    """The literal failure mode confirmed live: model returns
    channel='unclear' despite being given the real channel - must be
    corrected the same as any other mismatch, not specially rejected."""
    bad = dict(_VALID, channel="unclear")
    result = validate_interpretation(bad, expected_channel="policy_path")
    assert result["channel"] == "policy_path"


def test_matching_channel_passes_through_unchanged():
    ok = dict(_VALID, channel="policy_path")
    result = validate_interpretation(ok, expected_channel="policy_path")
    assert result["channel"] == "policy_path"


def test_entry_point_too_long_raises():
    bad = dict(_VALID, entry_point="This Entry Point Has Way Too Many Words")
    with pytest.raises(InterpretationValidationError):
        validate_interpretation(bad, expected_channel="policy_path")


def test_entry_point_unattributed_exempt_from_word_count():
    ok = dict(_VALID, entry_point="unattributed")
    result = validate_interpretation(ok, expected_channel="policy_path")
    assert result["entry_point"] == "unattributed"


def test_empty_assets_raises():
    bad = dict(_VALID, assets=[])
    with pytest.raises(InterpretationValidationError):
        validate_interpretation(bad, expected_channel="policy_path")


def test_too_many_assets_raises():
    bad = dict(_VALID, assets=["treasuries", "real_rates", "credit", "usd"])
    with pytest.raises(InterpretationValidationError):
        validate_interpretation(bad, expected_channel="policy_path")


def test_disallowed_asset_raises():
    bad = dict(_VALID, assets=["bitcoin"])
    with pytest.raises(InterpretationValidationError):
        validate_interpretation(bad, expected_channel="policy_path")


def test_transmission_too_long_raises():
    bad = dict(_VALID, transmission=" ".join(["word"] * 30))
    with pytest.raises(InterpretationValidationError):
        validate_interpretation(bad, expected_channel="policy_path")


def test_suspect_true_requires_reason():
    bad = dict(_VALID, suspect=True, suspect_reason=None)
    with pytest.raises(InterpretationValidationError):
        validate_interpretation(bad, expected_channel="policy_path")


def test_suspect_false_requires_null_reason():
    bad = dict(_VALID, suspect=False, suspect_reason="some reason")
    with pytest.raises(InterpretationValidationError):
        validate_interpretation(bad, expected_channel="policy_path")


def test_suspect_true_with_real_reason_passes():
    ok = dict(_VALID, suspect=True, suspect_reason="Thanksgiving holiday week distorted claims")
    result = validate_interpretation(ok, expected_channel="policy_path")
    assert result["suspect"] is True


@pytest.mark.parametrize("banned", [
    "signals that", "suggests", "could mean", "investors fear", "markets are watching",
])
def test_banned_commentary_language_raises(banned):
    bad = dict(_VALID, transmission=f"This move {banned} something important happened today in markets.")
    with pytest.raises(InterpretationValidationError):
        validate_interpretation(bad, expected_channel="policy_path")


@pytest.mark.parametrize("real_transmission", [
    # CONFIRMED LIVE - the exact real transmission text produced by a
    # 5-member WEAK-tier event with modest, mixed-direction moves and no
    # single dramatic number to describe (2026-09-11 real pipeline run).
    "No series breached the HIGH threshold; real yields and breakevens moved within their typical range and did not trigger a significant event.",
    # CONFIRMED LIVE, a second real occurrence (2026-09-21 real run).
    "No HIGH-tier moves were observed in real yields or the Treasury curve; recent changes remained within weaker bands.",
])
def test_tier_commentary_in_transmission_raises(real_transmission):
    """The model must describe what moved (mechanism), never narrate its
    own tier decision ('breached the threshold', 'did not trigger') -
    this is a real violation of Appendix A's 'it never classifies' rule
    that the original _BANNED_TERMS list did not catch, confirmed live
    on real WEAK-tier events with modest, mixed moves and nothing
    dramatic to describe."""
    bad = dict(_VALID, transmission=real_transmission)
    with pytest.raises(InterpretationValidationError):
        validate_interpretation(bad, expected_channel="policy_path")


def test_transmission_describing_a_real_modest_move_still_passes():
    """The fix must not be so broad it rejects a legitimate quiet-WEAK
    description that happens to mention a small number - only commentary
    ABOUT the tier decision itself is banned, not describing a small
    real move."""
    ok = dict(_VALID, transmission="Real yields drifted 3bp lower across the curve, a modest easing in the discount rate on long-duration cash flows.")
    result = validate_interpretation(ok, expected_channel="policy_path")
    assert result["transmission"] == ok["transmission"]

# ============================================================================
# Storage (insert_macro_signal_event)  (from test_macro_signal_jobs.py)
# ============================================================================

_ALLOWED_SIGNAL_DETECTION = {"signal", "weak_signal", "noise", "waiting"}


def _captured_params():
    """Returns (mock_conn, get_params) - get_params() reads back the
    tuple passed to conn.execute() after the call under test runs."""
    mock_conn = MagicMock()
    mock_get_db = MagicMock()
    mock_get_db.return_value.__enter__.return_value = mock_conn
    return mock_conn, mock_get_db


def test_suppressed_audit_row_signal_reason_names_the_rule():
    """A row suppressed by a specific rule (derived/collinear/confirmation)
    must carry that rule's name directly in signal_reason - not just
    buried in metadata - so 'why wasn't this on the page?' is a plain
    read of the row, matching the spec's own audit intent."""
    mock_conn, mock_get_db = _captured_params()
    event = {
        "series_id": "DGS10", "observation_date": "2026-08-28",
        "tier": "HIGH", "z_score": 1.258, "suppressed_by": "derived:DFII10+T10YIE",
    }
    with patch("models.jobs.get_db", mock_get_db):
        insert_macro_signal_event(job_id=1, event=event, interpretation=None)

    params = mock_conn.execute.call_args.args[1]
    signal_reason = params[3]  # positional order matches the INSERT's column list
    assert "Suppressed by rule" in signal_reason
    assert "derived:DFII10+T10YIE" in signal_reason


def test_noise_audit_row_signal_reason_explains_no_threshold_cleared():
    """A genuine NOISE observation (never cleared any tier, nothing
    suppressed it because there was nothing to suppress) must get a
    distinct, honest explanation - not the same wording as an actively
    suppressed row, since those are different situations."""
    mock_conn, mock_get_db = _captured_params()
    event = {
        "series_id": "DGS10", "observation_date": "2026-08-27",
        "tier": "NOISE", "z_score": 0.21, "suppressed_by": None,
    }
    with patch("models.jobs.get_db", mock_get_db):
        insert_macro_signal_event(job_id=1, event=event, interpretation=None)

    params = mock_conn.execute.call_args.args[1]
    signal_reason = params[3]
    assert "NOISE" in signal_reason
    assert "Suppressed by rule" not in signal_reason


def test_audit_row_signal_detection_matches_db_check_constraint():
    """CONFIRMED LIVE: agent_classifications_signal_detection_check only
    allows 'signal'/'weak_signal'/'noise'/'waiting' - a naive
    str(tier).lower() produces 'high'/'weak'/'noise', and the first two
    violate the constraint (a real INSERT failure hit during the first
    live end-to-end pipeline run against real data). Every tier must map
    to an allowed value."""
    for tier, expected in [("HIGH", "signal"), ("WEAK", "weak_signal"), ("NOISE", "noise")]:
        mock_conn, mock_get_db = _captured_params()
        event = {
            "series_id": "DGS10", "observation_date": "2026-08-28",
            "tier": tier, "z_score": 1.0, "suppressed_by": None,
        }
        with patch("models.jobs.get_db", mock_get_db):
            insert_macro_signal_event(job_id=1, event=event, interpretation=None)

        params = mock_conn.execute.call_args.args[1]
        signal_detection = params[2]
        assert signal_detection == expected, f"tier={tier} produced {signal_detection!r}, expected {expected!r}"
        assert signal_detection in _ALLOWED_SIGNAL_DETECTION


def test_interpreted_event_signal_reason_is_the_llm_transmission():
    """An interpreted survivor's signal_reason must still be the LLM's
    own transmission sentence, unaffected by the audit-row wording
    above - this is the existing, already-correct behavior for the
    non-None interpretation path."""
    mock_conn, mock_get_db = _captured_params()
    event = {
        "release_id": 18, "knowledge_time": "2026-08-28T20:30:00+00:00",
        "tier": "HIGH", "member_series": ["DFII5"], "z_scores": {"DFII5": 2.472},
    }
    interpretation = {
        "channel": "discount_rate", "entry_point": "unattributed",
        "assets": ["real_rates"],
        "transmission": "Real yields rose 11bp, raising the discount rate on near-term cash flows.",
        "suspect": False, "suspect_reason": None,
    }
    with patch("models.jobs.get_db", mock_get_db):
        insert_macro_signal_event(job_id=1, event=event, interpretation=interpretation)

    params = mock_conn.execute.call_args.args[1]
    signal_reason = params[3]
    assert signal_reason == interpretation["transmission"]

# ============================================================================
# Full pipeline (run_macro_signal_pipeline) - integration  (from test_macro_signal_pipeline.py)
# ============================================================================

def _synthetic_observations(series_id: str, target_date: date, target_value: float) -> list[dict]:
    """400 days of quiet, low-variance history, then a real move on
    target_date - enough for rolling_zscore's 30-observation minimum and
    a clean, large z-score on the target date."""
    obs = []
    value = 4.00
    start = target_date - timedelta(days=400)
    d = start
    while d < target_date:
        obs.append({"series_id": series_id, "observation_date": d, "value": round(value, 4)})
        value += 0.0005 if (d.toordinal() % 2 == 0) else -0.0005
        d += timedelta(days=1)
    obs.append({"series_id": series_id, "observation_date": target_date, "value": target_value})
    return obs


def test_run_macro_signal_pipeline_end_to_end():
    target_date = date(2026, 8, 28)
    from_date = target_date.isoformat()
    to_date = target_date.isoformat()

    # DFII5 and DGS1 both move enough to be HIGH on the target date, real
    # spec worked-example shape (though not exact values - just needs to
    # clear the HIGH floor with a clean z-score against quiet history).
    all_obs = (
        _synthetic_observations("DFII5", target_date, 4.30)
        + _synthetic_observations("DGS1", target_date, 4.35)
    )

    fake_interpretation = {
        "channel": "discount_rate",
        "entry_point": "unattributed",
        "assets": ["treasuries", "real_rates"],
        "transmission": "Real yields moved on a repricing of the policy path.",
        "suspect": False,
        "suspect_reason": None,
    }

    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=all_obs)), \
         patch("controllers.run.interpret_events_batch") as mock_interpret, \
         patch("controllers.run.update_job_status") as mock_status, \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.insert_macro_signal_event") as mock_insert:

        def _fake_interpret(payloads):
            return [{"event": p, "interpretation": fake_interpretation} for p in payloads]
        mock_interpret.side_effect = _fake_interpret

        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=1, from_date=from_date, to_date=to_date))

    mock_status.assert_any_call(1, "running")
    # Final call should mark completed with at least 1 inserted event
    final_call = mock_status.call_args_list[-1]
    assert final_call.args[1] == "completed" or final_call.kwargs.get("status") == "completed"

    # Both DFII5 and DGS1 fired (different channels: discount_rate vs
    # policy_path) -> per the collapse decision, they do NOT merge into
    # one event - two separate insert_macro_signal_event calls expected,
    # both with a real interpretation (not None).
    interpreted_calls = [c for c in mock_insert.call_args_list if c.args[2] is not None]
    assert len(interpreted_calls) == 2


def test_run_macro_signal_pipeline_no_observations_completes_with_zero():
    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=[])), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.update_job_status") as mock_status:
        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=2, from_date="2026-08-28", to_date="2026-08-28"))

    mock_status.assert_any_call(2, "completed", article_count=0, set_completed_at=True)


def test_run_macro_signal_pipeline_noise_series_never_reaches_interpret():
    """A series whose move never clears NOISE should never appear in an
    interpret_events_batch call."""
    target_date = date(2026, 8, 28)
    # Flat series - no real move on target_date at all.
    obs = []
    d = target_date - timedelta(days=400)
    while d <= target_date:
        obs.append({"series_id": "DFII5", "observation_date": d, "value": 4.00})
        d += timedelta(days=1)

    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch") as mock_interpret, \
         patch("controllers.run.update_job_status"), \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.insert_macro_signal_event"):
        mock_interpret.return_value = []
        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=3, from_date=target_date.isoformat(), to_date=target_date.isoformat()))

    # interpret_events_batch called with an empty (or no-HIGH/WEAK) payload list
    call_args = mock_interpret.call_args
    if call_args is not None:
        assert call_args.args[0] == []


def test_run_macro_signal_pipeline_dff_inter_meeting_move_tiers_high():
    """DFF wiring: an inter-meeting move (observation_date not scheduled)
    must tier HIGH with no size/z-gate, per _dff_rule's own no-gate path."""
    target_date = date(2026, 8, 28)  # deliberately not a real FOMC date
    obs = []
    value = 4.00
    d = target_date - timedelta(days=400)
    while d < target_date:
        obs.append({"series_id": "DFF", "observation_date": d, "value": round(value, 4)})
        value += 0.0005 if (d.toordinal() % 2 == 0) else -0.0005
        d += timedelta(days=1)
    obs.append({"series_id": "DFF", "observation_date": target_date, "value": round(value, 4) + 0.0002})  # tiny move - would be NOISE/WEAK under the size-gated path

    fake_interpretation = {
        "channel": "policy_path", "entry_point": "unattributed",
        "assets": ["treasuries"], "transmission": "The Fed moved the funds rate outside a scheduled meeting.",
        "suspect": False, "suspect_reason": None,
    }

    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch") as mock_interpret, \
         patch("controllers.run.update_job_status") as mock_status, \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.is_within_known_calendar_horizon", return_value=True), \
         patch("controllers.run.is_scheduled_fomc_date", return_value=False), \
         patch("controllers.run.insert_macro_signal_event") as mock_insert:

        def _fake_interpret(payloads):
            return [{"event": p, "interpretation": fake_interpretation} for p in payloads]
        mock_interpret.side_effect = _fake_interpret

        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=10, from_date=target_date.isoformat(), to_date=target_date.isoformat()))

    interpreted_calls = [c for c in mock_insert.call_args_list if c.args[2] is not None]
    assert len(interpreted_calls) == 1
    assert interpreted_calls[0].args[1]["tier"] == "HIGH"


def test_run_macro_signal_pipeline_dff_flat_rate_on_unscheduled_date_is_not_inter_meeting():
    """Regression test for a real bug found live (2026-09-24, real 30-day
    classify run): DFF sitting FLAT (change_bp==0) on several consecutive
    non-scheduled days was wrongly treated as 4 separate inter-meeting
    MOVES (is_inter_meeting_date = not is_scheduled_fomc_date(date),
    with no check that a move actually happened) - each fired the
    no-gate HIGH path in _dff_rule off a z_score of 0.0. An
    inter-meeting move requires BOTH a real change AND a non-scheduled
    date; a quiet day between meetings must tier NOISE like any other
    unremarkable day, never HIGH."""
    target_date = date(2026, 8, 28)  # not a real FOMC date
    obs = []
    value = 4.00
    d = target_date - timedelta(days=400)
    last_value = value
    while d < target_date:
        obs.append({"series_id": "DFF", "observation_date": d, "value": round(value, 4)})
        last_value = round(value, 4)
        value += 0.0005 if (d.toordinal() % 2 == 0) else -0.0005
        d += timedelta(days=1)
    # Flat - the exact same value as the immediately preceding day, zero change.
    obs.append({"series_id": "DFF", "observation_date": target_date, "value": last_value})

    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch") as mock_interpret, \
         patch("controllers.run.update_job_status"), \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.is_within_known_calendar_horizon", return_value=True), \
         patch("controllers.run.is_scheduled_fomc_date", return_value=False), \
         patch("controllers.run.insert_macro_signal_event"):
        mock_interpret.return_value = []
        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=18, from_date=target_date.isoformat(), to_date=target_date.isoformat()))

    call_args = mock_interpret.call_args
    if call_args is not None:
        assert call_args.args[0] == []


def test_run_macro_signal_pipeline_interpret_payload_carries_real_move_not_level():
    """Regression test for a real bug found live (2026-09-24 audit):
    T10Y2Y went 0.26 -> 0.31 (a real +5bp move) but INTERPRET's output
    said "steepened by 31bp" - the model was only ever given `value`
    (the raw level, 0.31) and had no real move field, so it silently
    reported the level as if it were the change. Same root cause
    produced "widened 92bp" for a real +12bp T10Y3M move, and a
    fabricated "375bp" for FEDTARMD (whose payload had no move number
    at all to anchor on). Fixed by threading move_bp (SuppressibleResult)
    through to the interpret payload - this test locks in that the
    payload's members carry the real move_bp, distinct from the level,
    so INTERPRET always has the correct number instead of guessing."""
    target_date = date(2026, 9, 24)
    obs = []
    d = target_date - timedelta(days=400)
    value = 0.20
    while d < target_date:
        obs.append({"series_id": "T10Y2Y", "observation_date": d, "value": round(value, 4)})
        value += 0.0002 if (d.toordinal() % 2 == 0) else -0.0002
        d += timedelta(days=1)
    # Real reported bug: 0.26 -> 0.31, a +5bp move, but `value` (31 once
    # read as bp) is nowhere close to the real move.
    obs.append({"series_id": "T10Y2Y", "observation_date": target_date - timedelta(days=1), "value": 0.26})
    obs.append({"series_id": "T10Y2Y", "observation_date": target_date, "value": 0.31})

    captured_payloads = []

    def _fake_interpret(payloads):
        captured_payloads.extend(payloads)
        return []

    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch", side_effect=_fake_interpret), \
         patch("controllers.run.update_job_status"), \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.insert_macro_signal_event"):
        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=30, from_date=target_date.isoformat(), to_date=target_date.isoformat()))

    assert captured_payloads, "T10Y2Y's real move should have cleared HIGH/WEAK and reached INTERPRET"
    member = next(m for p in captured_payloads for m in p["members"] if m["series_id"] == "T10Y2Y")
    assert member["value"] == 0.31
    assert member["move_bp"] is not None
    assert member["move_bp"] == 5.0, f"expected the exact +5bp move, got move_bp={member['move_bp']}"
    assert round(member["move_bp"]) != round(member["value"] * 100), (
        "move_bp must never equal value*100 - that's exactly the bug (level misread as move)"
    )


def test_run_macro_signal_pipeline_standard_series_event_carries_prior_and_current_values():
    """Real ask (frontend ticket, 2026-09-25, item 2b): prior_values was
    empty on 28 of 29 events - only FEDTARMD had it wired. This test
    covers a STANDARD (non-FEDTARMD) series end to end against the
    actual insert_macro_signal_event call (the real stored-metadata
    boundary, not just the interpret payload) - T10Y2Y going 0.26 ->
    0.31 must produce current_values.T10Y2Y == "0.31" and
    prior_values.T10Y2Y == "0.26", both as strings, and move_bp exactly
    5.0 (not 4.99 or any float-imprecise value)."""
    target_date = date(2026, 9, 24)
    obs = []
    d = target_date - timedelta(days=400)
    value = 0.20
    while d < target_date - timedelta(days=1):
        obs.append({"series_id": "T10Y2Y", "observation_date": d, "value": str(round(value, 4))})
        value += 0.0002 if (d.toordinal() % 2 == 0) else -0.0002
        d += timedelta(days=1)
    obs.append({"series_id": "T10Y2Y", "observation_date": target_date - timedelta(days=1), "value": "0.26"})
    obs.append({"series_id": "T10Y2Y", "observation_date": target_date, "value": "0.31"})

    fake_interpretation = {
        "channel": "discount_rate", "entry_point": "unattributed",
        "assets": ["treasuries"], "transmission": "The 2s10s Treasury curve steepened by 5bp.",
        "suspect": False, "suspect_reason": None,
    }

    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch") as mock_interpret, \
         patch("controllers.run.update_job_status"), \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.insert_macro_signal_event") as mock_insert:

        def _fake_interpret(payloads):
            return [{"event": p, "interpretation": fake_interpretation} for p in payloads]
        mock_interpret.side_effect = _fake_interpret

        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=32, from_date=target_date.isoformat(), to_date=target_date.isoformat()))

    interpreted_calls = [c for c in mock_insert.call_args_list if c.args[2] is not None]
    assert len(interpreted_calls) == 1, f"expected exactly 1 interpreted event, got {len(interpreted_calls)}"
    stored_event = interpreted_calls[0].args[1]
    assert stored_event["move_bp"]["T10Y2Y"] == 5.0
    assert stored_event["current_values"]["T10Y2Y"] == "0.31"
    assert stored_event["prior_values"]["T10Y2Y"] == "0.26"
    assert isinstance(stored_event["current_values"]["T10Y2Y"], str)
    assert isinstance(stored_event["prior_values"]["T10Y2Y"], str)
    # Real ask (frontend follow-up, 2026-09-25): classification_reason
    # reaches stored metadata for a STANDARD series too, not just
    # FEDTARMD - "1-day move of 5bp cleared the 4bp WEAK floor" matches
    # the ticket's own T10Y2Y worked example exactly.
    reason = stored_event["classification_reason"]["T10Y2Y"]
    assert reason.startswith("1-day move of 5bp cleared the 4bp WEAK floor (z = ")
    assert reason.endswith(").")


def test_run_macro_signal_pipeline_fedtarmd_event_carries_classification_basis_and_exact_move_bp():
    """Real frontend follow-up ticket (after job 258, 2026-09-25): the
    FOMC event's move_bp/target_years/text are now correct, but (1)
    z_scores.FEDTARMD is still null with nothing explaining WHAT rule
    made it HIGH, and (2) move_bp arrives with float noise (e.g.
    4.999999999999999, 6.00000000000005).

    Fixes: classification_basis (TierResult.reason, e.g.
    "sep_median_shift_50.0bp_ge_25_no_zgate") now stored per series.
    move_bp: a first fix (truncate to 2dp) was itself reported wrong by
    the frontend - truncating 49.99999999999996 gives 49.99, not the
    real exact value 50, and disagreed with the event text and
    classification_basis. The real fix is upstream: Decimal(str(value))
    arithmetic in macro_signal_fedtarmd.py (not float()) is exact, so no
    rounding/truncation step is needed anywhere downstream - this test
    asserts the EXACT value (50.0, not 49.99) now comes out the other
    end. Also asserts current_values/prior_values are both present and
    are strings (real ask: prior_values was missing on 28 of 29 events,
    and FEDTARMD's own prior_value was a bare float, not a string like
    current_values). Asserts on the actual insert_macro_signal_event
    call (the real stored-metadata boundary), not just the interpret
    payload."""
    snapshots = {
        date(2026, 6, 17): {2026: 3.8, 2027: 3.6, 2028: 3.4},
        date(2026, 9, 16): {2026: 4.1, 2027: 4.1, 2028: 3.9, 2029: 3.6},
    }
    obs = _observations_from_snapshots(snapshots)

    fake_interpretation = {
        "channel": "policy_path", "entry_point": "FOMC decision",
        "assets": ["treasuries"], "transmission": "The 2027 median dot rose 50bp.",
        "suspect": False, "suspect_reason": None,
    }

    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch") as mock_interpret, \
         patch("controllers.run.update_job_status"), \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.insert_macro_signal_event") as mock_insert:

        def _fake_interpret(payloads):
            return [{"event": p, "interpretation": fake_interpretation} for p in payloads]
        mock_interpret.side_effect = _fake_interpret

        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=31, from_date="2026-09-16", to_date="2026-09-16"))

    interpreted_calls = [c for c in mock_insert.call_args_list if c.args[2] is not None]
    assert len(interpreted_calls) == 1
    stored_event = interpreted_calls[0].args[1]
    assert stored_event["z_scores"]["FEDTARMD"] is None  # still null by design, no z-gate rule
    assert stored_event["classification_basis"]["FEDTARMD"] is not None
    assert "sep_median_shift" in stored_event["classification_basis"]["FEDTARMD"]
    assert stored_event["move_bp"]["FEDTARMD"] == 50.0  # exact, not 49.99 - real values are 3.6 -> 4.1
    assert stored_event["current_values"]["FEDTARMD"] == "4.1"
    assert stored_event["prior_values"]["FEDTARMD"] == "3.6"
    assert isinstance(stored_event["current_values"]["FEDTARMD"], str)
    assert isinstance(stored_event["prior_values"]["FEDTARMD"], str)
    # Real ask (frontend follow-up, 2026-09-25): classification_reason -
    # a real plain-English sentence, not the machine-readable
    # classification_basis tag - matches the ticket's own worked example
    # exactly: "The 2027 SEP median moved 50bp, above the 25bp HIGH
    # threshold (no z-score check)."
    assert stored_event["classification_reason"]["FEDTARMD"] == (
        "The SEP median moved 50bp, above the 25bp HIGH threshold (no z-score check)."
    )


def test_run_macro_signal_pipeline_dff_past_calendar_horizon_is_skipped_not_guessed():
    """A DFF observation past the known FOMC calendar horizon must be
    skipped entirely (logged), never tiered by guessing inter-meeting
    status - see is_within_known_calendar_horizon's own fail-closed
    contract."""
    target_date = date(2026, 8, 28)
    obs = []
    value = 4.00
    d = target_date - timedelta(days=400)
    while d < target_date:
        obs.append({"series_id": "DFF", "observation_date": d, "value": round(value, 4)})
        value += 0.0005 if (d.toordinal() % 2 == 0) else -0.0005
        d += timedelta(days=1)
    obs.append({"series_id": "DFF", "observation_date": target_date, "value": 4.50})  # a real move, but must still be skipped

    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch") as mock_interpret, \
         patch("controllers.run.update_job_status"), \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.is_within_known_calendar_horizon", return_value=False), \
         patch("controllers.run.insert_macro_signal_event"):
        mock_interpret.return_value = []
        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=12, from_date=target_date.isoformat(), to_date=target_date.isoformat()))

    call_args = mock_interpret.call_args
    if call_args is not None:
        assert call_args.args[0] == []


def test_run_macro_signal_pipeline_fedtarmd_large_shift_tiers_high():
    """FEDTARMD wiring: a >=25bp same-target-year SEP median shift
    across two real releases must tier HIGH with no z-gate."""
    prior_release = date(2026, 6, 17)
    current_release = date(2026, 9, 16)
    obs = [
        {"series_id": "FEDTARMD", "observation_date": date(2026, 1, 1), "value": 3.8, "vintage": prior_release},
        {"series_id": "FEDTARMD", "observation_date": date(2027, 1, 1), "value": 3.6, "vintage": prior_release},
        {"series_id": "FEDTARMD", "observation_date": date(2026, 1, 1), "value": 4.1, "vintage": current_release},
        {"series_id": "FEDTARMD", "observation_date": date(2027, 1, 1), "value": 4.1, "vintage": current_release},  # +0.5pp = +50bp vs prior
    ]

    fake_interpretation = {
        "channel": "policy_path", "entry_point": "unattributed",
        "assets": ["treasuries"], "transmission": "The Fed's own dot plot shifted its rate outlook meaningfully higher.",
        "suspect": False, "suspect_reason": None,
    }

    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch") as mock_interpret, \
         patch("controllers.run.update_job_status") as mock_status, \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.insert_macro_signal_event") as mock_insert:

        def _fake_interpret(payloads):
            return [{"event": p, "interpretation": fake_interpretation} for p in payloads]
        mock_interpret.side_effect = _fake_interpret

        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=13, from_date=current_release.isoformat(), to_date=current_release.isoformat()))

    interpreted_calls = [c for c in mock_insert.call_args_list if c.args[2] is not None]
    assert len(interpreted_calls) == 1
    assert interpreted_calls[0].args[1]["tier"] == "HIGH"


def test_run_macro_signal_pipeline_fedtarmd_far_future_target_year_not_dropped_by_date_bound():
    """Regression test for the exact bug found live: FEDTARMD's
    observation_date is the PROJECTED TARGET YEAR (e.g. 2029), which can
    fall outside to_date's bound even though the real release itself
    (vintage) is current - the pipeline must still tier it, proving the
    unbounded FEDTARMD-specific fetch is actually wired in and used."""
    prior_release = date(2026, 6, 17)
    current_release = date(2026, 9, 16)
    obs = [
        # Every observation_date here is years past to_date=current_release
        # below - if the general from_date/to_date-bounded fetch were the
        # only source, none of this would ever be tiered.
        {"series_id": "FEDTARMD", "observation_date": date(2027, 1, 1), "value": 3.6, "vintage": prior_release},
        {"series_id": "FEDTARMD", "observation_date": date(2028, 1, 1), "value": 3.4, "vintage": prior_release},
        {"series_id": "FEDTARMD", "observation_date": date(2027, 1, 1), "value": 4.1, "vintage": current_release},
        {"series_id": "FEDTARMD", "observation_date": date(2028, 1, 1), "value": 3.9, "vintage": current_release},
    ]

    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch") as mock_interpret, \
         patch("controllers.run.update_job_status"), \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.insert_macro_signal_event"):
        mock_interpret.return_value = []
        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=14, from_date=current_release.isoformat(), to_date=current_release.isoformat()))

    # FEDTARMD was tiered at all (interpret_events_batch got called with
    # a non-empty candidate list before NOISE-filtering, OR the event
    # made it through) - proven by mock_interpret having been invoked
    # with the FEDTARMD move considered, not skipped as out-of-range.
    mock_interpret.assert_called_once()


def test_run_macro_signal_pipeline_attaches_dfedtaru_ctx_bp_to_policy_path_events():
    """DFEDTARU is excluded from tiering entirely (spec) but its own
    current level is real grounding context for a policy_path channel
    event - attached as dfedtaru_ctx_bp (in bp, matching every other
    series' native unit convention) on the interpret payload, looked up
    as the most recent DFEDTARU value on or before the event's
    knowledge_time."""
    target_date = date(2026, 8, 28)
    obs = []
    value = 4.00
    d = target_date - timedelta(days=400)
    while d < target_date:
        obs.append({"series_id": "DGS1", "observation_date": d, "value": round(value, 4)})
        value += 0.0005 if (d.toordinal() % 2 == 0) else -0.0005
        d += timedelta(days=1)
    obs.append({"series_id": "DGS1", "observation_date": target_date, "value": 4.35})  # real HIGH move -> policy_path event
    # DFEDTARU: flat at 4.125% (412.5bp) through and past the event date -
    # a real daily market-close series, present but never tiered.
    d = target_date - timedelta(days=10)
    while d <= target_date:
        obs.append({"series_id": "DFEDTARU", "observation_date": d, "value": 4.125})
        d += timedelta(days=1)

    captured_payloads = []

    def _fake_interpret(payloads):
        captured_payloads.extend(payloads)
        return []
    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch", side_effect=_fake_interpret), \
         patch("controllers.run.update_job_status"), \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.insert_macro_signal_event"):
        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=15, from_date=target_date.isoformat(), to_date=target_date.isoformat()))

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    assert payload["channel"] == "policy_path"
    assert payload["dfedtaru_ctx_bp"] == pytest.approx(412.5)


def test_run_macro_signal_pipeline_no_dfedtaru_ctx_bp_for_non_policy_path_events():
    """A discount_rate channel event must NOT get dfedtaru_ctx_bp - it's
    only meaningful context for policy_path events."""
    target_date = date(2026, 8, 28)
    obs = []
    value = 4.00
    d = target_date - timedelta(days=400)
    while d < target_date:
        obs.append({"series_id": "DFII5", "observation_date": d, "value": round(value, 4)})
        value += 0.0005 if (d.toordinal() % 2 == 0) else -0.0005
        d += timedelta(days=1)
    obs.append({"series_id": "DFII5", "observation_date": target_date, "value": 4.30})
    d = target_date - timedelta(days=10)
    while d <= target_date:
        obs.append({"series_id": "DFEDTARU", "observation_date": d, "value": 4.125})
        d += timedelta(days=1)

    captured_payloads = []

    def _fake_interpret(payloads):
        captured_payloads.extend(payloads)
        return []
    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch", side_effect=_fake_interpret), \
         patch("controllers.run.update_job_status"), \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.insert_macro_signal_event"):
        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=16, from_date=target_date.isoformat(), to_date=target_date.isoformat()))

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]
    assert payload["channel"] == "discount_rate"
    assert "dfedtaru_ctx_bp" not in payload


def test_run_macro_signal_pipeline_no_dfedtaru_ctx_bp_when_dfedtaru_absent():
    """No DFEDTARU data at all (e.g. news-retrieval fetch gap) must
    degrade to simply omitting the field, never a crash or a fabricated
    value."""
    target_date = date(2026, 8, 28)
    obs = []
    value = 4.00
    d = target_date - timedelta(days=400)
    while d < target_date:
        obs.append({"series_id": "DGS1", "observation_date": d, "value": round(value, 4)})
        value += 0.0005 if (d.toordinal() % 2 == 0) else -0.0005
        d += timedelta(days=1)
    obs.append({"series_id": "DGS1", "observation_date": target_date, "value": 4.35})

    captured_payloads = []

    def _fake_interpret(payloads):
        captured_payloads.extend(payloads)
        return []
    with patch("controllers.run.get_macro_observations", new=AsyncMock(return_value=obs)), \
         patch("controllers.run.interpret_events_batch", side_effect=_fake_interpret), \
         patch("controllers.run.update_job_status"), \
         patch("controllers.run.get_existing_macro_signal_source_ids", return_value=set()), \
         patch("controllers.run.calendar_staleness_warning", return_value=None), \
         patch("controllers.run.insert_macro_signal_event"):
        from controllers.run import run_macro_signal_pipeline
        asyncio.run(run_macro_signal_pipeline(job_id=17, from_date=target_date.isoformat(), to_date=target_date.isoformat()))

    assert len(captured_payloads) == 1
    assert "dfedtaru_ctx_bp" not in captured_payloads[0]

# ============================================================================
# Full chain (POST /macro/run + POST /macro/fetch) - HTTP integration  (from test_macro_signal_run_chain.py)
# ============================================================================

def test_trigger_macro_fetch_returns_run_id_on_202():
    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.json.return_value = {"run_id": 57, "status": "running"}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("adapters.news_client.httpx.AsyncClient", return_value=mock_client):
        from adapters.news_client import trigger_macro_fetch
        run_id = asyncio.run(trigger_macro_fetch(incremental=True))

    assert run_id == 57
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["json"] == {"incremental": True}


def test_trigger_macro_fetch_raises_on_unexpected_status():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "internal error"

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("adapters.news_client.httpx.AsyncClient", return_value=mock_client):
        from adapters.news_client import NewsRetrievalError, trigger_macro_fetch
        with pytest.raises(NewsRetrievalError):
            asyncio.run(trigger_macro_fetch(incremental=False))


def test_full_chain_triggers_fetch_waits_refreshes_calendar_then_pipelines():
    with patch("controllers.run.trigger_macro_fetch", new=AsyncMock(return_value=57)) as mock_trigger, \
         patch("controllers.run.poll_run_until_done", new=AsyncMock()) as mock_poll, \
         patch("controllers.run.refresh_fomc_meeting_dates", return_value=11) as mock_refresh, \
         patch("controllers.run.run_macro_signal_pipeline", new=AsyncMock()) as mock_pipeline, \
         patch("controllers.run.update_job_status") as mock_status:
        from controllers.run import run_macro_signal_full_chain
        asyncio.run(run_macro_signal_full_chain(
            job_id=1, from_date="2026-09-17", to_date="2026-09-17", incremental=True,
        ))

    mock_trigger.assert_called_once_with(incremental=True)
    mock_poll.assert_called_once_with(57)
    mock_refresh.assert_called_once()
    mock_pipeline.assert_called_once_with(1, "2026-09-17", "2026-09-17")
    mock_status.assert_any_call(1, "running")


def test_full_chain_marks_job_failed_when_fetch_fails():
    from adapters.news_client import NewsRetrievalError
    with patch("controllers.run.trigger_macro_fetch", new=AsyncMock(side_effect=NewsRetrievalError("boom"))), \
         patch("controllers.run.poll_run_until_done", new=AsyncMock()) as mock_poll, \
         patch("controllers.run.refresh_fomc_meeting_dates") as mock_refresh, \
         patch("controllers.run.run_macro_signal_pipeline", new=AsyncMock()) as mock_pipeline, \
         patch("controllers.run.update_job_status") as mock_status:
        from controllers.run import run_macro_signal_full_chain
        asyncio.run(run_macro_signal_full_chain(
            job_id=2, from_date="2026-09-17", to_date="2026-09-17", incremental=False,
        ))

    mock_poll.assert_not_called()
    mock_refresh.assert_not_called()
    mock_pipeline.assert_not_called()
    mock_status.assert_any_call(2, "failed", set_completed_at=True)


def test_full_chain_continues_past_calendar_refresh_failure():
    """A calendar refresh failure degrades DFF's inter-meeting detection
    but must not abort a real fetch+backfill that already succeeded -
    the pipeline still runs."""
    with patch("controllers.run.trigger_macro_fetch", new=AsyncMock(return_value=57)), \
         patch("controllers.run.poll_run_until_done", new=AsyncMock()), \
         patch("controllers.run.refresh_fomc_meeting_dates", side_effect=RuntimeError("feed down")), \
         patch("controllers.run.run_macro_signal_pipeline", new=AsyncMock()) as mock_pipeline, \
         patch("controllers.run.update_job_status"):
        from controllers.run import run_macro_signal_full_chain
        asyncio.run(run_macro_signal_full_chain(
            job_id=3, from_date="2026-09-17", to_date="2026-09-17", incremental=True,
        ))

    mock_pipeline.assert_called_once()


def _admin_caller_header() -> str:
    import base64
    import json
    return base64.b64encode(json.dumps({"sub": 0, "role": "admin", "domains": []}).encode()).decode()


def test_post_macro_run_creates_job_and_returns_202():
    from fastapi.testclient import TestClient

    with patch("routes.macro.create_job", return_value=88) as mock_create_job, \
         patch("routes.macro.run_macro_signal_full_chain"):
        import app as app_module
        client = TestClient(app_module.create_app())
        resp = client.post(
            "/macro/run",
            json={"incremental": True, "today": True},
            headers={"x-ocn-caller": _admin_caller_header()},
        )

    assert resp.status_code == 202
    assert resp.json() == {"job_id": 88, "status": "running"}
    mock_create_job.assert_called_once()


def test_post_macro_run_defaults_to_yesterday_when_today_false():
    from datetime import datetime, timedelta, timezone
    from fastapi.testclient import TestClient

    captured = {}

    def _fake_add_task(fn, job_id, from_date, to_date, *, incremental):
        captured["from_date"] = from_date
        captured["to_date"] = to_date

    with patch("routes.macro.create_job", return_value=89), \
         patch("fastapi.BackgroundTasks.add_task", side_effect=_fake_add_task):
        import app as app_module
        client = TestClient(app_module.create_app())
        resp = client.post(
            "/macro/run",
            json={},
            headers={"x-ocn-caller": _admin_caller_header()},
        )

    assert resp.status_code == 202
    expected_yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    assert captured["from_date"] == expected_yesterday
    assert captured["to_date"] == expected_yesterday


# ============================================================================
# GET /results/summary route wiring (real ask: frontend ticket, 2026-09-25)
# ============================================================================

def test_get_results_summary_requires_auth():
    from fastapi.testclient import TestClient
    import app as app_module

    client = TestClient(app_module.create_app())
    resp = client.get("/results/summary", params={"source_type": "macro_signal"})
    assert resp.status_code == 401


def test_get_results_summary_requires_source_type():
    from fastapi.testclient import TestClient
    import app as app_module

    client = TestClient(app_module.create_app())
    resp = client.get("/results/summary", headers={"x-ocn-caller": _admin_caller_header()})
    assert resp.status_code == 422  # missing required query param


def test_get_results_summary_fetches_series_total_for_macro_signal(monkeypatch):
    from fastapi.testclient import TestClient

    fake_summary = {
        "window": {"from": "2026-08-26", "to": "2026-09-25"},
        "observations": {"total": 403, "high": 11, "weak": 60, "noise": 332, "suppressed": 9},
        "events": {"high": 5, "weak": 24},
        "series_reporting": 28,
        "last_run_at": "2026-09-25T12:44:00Z",
    }
    with patch("routes.jobs.get_results_summary", return_value=fake_summary), \
         patch("routes.jobs.fetch_macro_series_total", new=AsyncMock(return_value=46)):
        import app as app_module
        client = TestClient(app_module.create_app())
        resp = client.get(
            "/results/summary",
            params={"source_type": "macro_signal", "published_from": "2026-08-26", "published_to": "2026-09-25"},
            headers={"x-ocn-caller": _admin_caller_header()},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["series_total"] == 46
    assert body["observations"]["noise"] == 332  # passes the model layer's numbers through unchanged


def test_get_results_summary_series_total_none_for_non_macro_source_type():
    """series_total is only a meaningful concept for macro_signal (the
    only source_type with a real "total tracked series" universe) -
    must be None for every other source_type, and must NOT call
    news-retrieval at all for those (no wasted HTTP round-trip)."""
    from fastapi.testclient import TestClient

    fake_summary = {
        "window": {"from": None, "to": None},
        "observations": {"total": 0, "high": 0, "weak": 0, "noise": 0, "suppressed": 0},
        "events": {"high": 0, "weak": 0},
        "series_reporting": 0,
        "last_run_at": None,
    }
    with patch("routes.jobs.get_results_summary", return_value=fake_summary), \
         patch("routes.jobs.fetch_macro_series_total", new=AsyncMock(return_value=46)) as mock_fetch:
        import app as app_module
        client = TestClient(app_module.create_app())
        resp = client.get(
            "/results/summary",
            params={"source_type": "geopolitical_signal"},
            headers={"x-ocn-caller": _admin_caller_header()},
        )

    assert resp.status_code == 200
    assert resp.json()["series_total"] is None
    mock_fetch.assert_not_called()
