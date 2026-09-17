"""Unit tests for Stage C's deterministic override rules."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pipeline.geopolitical_signal_overrides import apply_overrides


def test_taiwan_conflict_forces_four_categories():
    result = apply_overrides(
        channel="conflict",
        actors=["China", "Taiwan"],
        assets=["broad_equities"],
        impacted_categories=[],
    )
    assert set(result) == {
        "Semiconductor Manufacturing",
        "Compute Hardware & Edge Systems",
        "Networking, Optical & Interconnect",
        "Cloud & Compute Platforms",
    }


def test_taiwan_strait_actor_phrasing_also_triggers_rule_1():
    result = apply_overrides(
        channel="conflict",
        actors=["Taiwan Strait"],
        assets=[],
        impacted_categories=[],
    )
    assert "Semiconductor Manufacturing" in result


def test_taiwan_actor_without_conflict_channel_does_not_trigger():
    result = apply_overrides(
        channel="trade",
        actors=["Taiwan"],
        assets=[],
        impacted_categories=[],
    )
    assert result == []


def test_conflict_channel_without_taiwan_actor_does_not_trigger():
    result = apply_overrides(
        channel="conflict",
        actors=["Russia", "Ukraine"],
        assets=[],
        impacted_categories=[],
    )
    assert "Semiconductor Manufacturing" not in result


def test_us_china_semis_trade_forces_semiconductor_manufacturing():
    result = apply_overrides(
        channel="trade",
        actors=["US", "China"],
        assets=["semis"],
        impacted_categories=[],
    )
    assert "Semiconductor Manufacturing" in result


def test_us_china_semis_sanctions_also_triggers_rule_2():
    result = apply_overrides(
        channel="sanctions",
        actors=["US", "China"],
        assets=["semis"],
        impacted_categories=[],
    )
    assert "Semiconductor Manufacturing" in result


def test_us_china_without_semis_asset_does_not_trigger_rule_2():
    result = apply_overrides(
        channel="trade",
        actors=["US", "China"],
        assets=["broad_equities"],
        impacted_categories=[],
    )
    assert result == []


def test_semis_asset_without_both_actors_does_not_trigger():
    result = apply_overrides(
        channel="trade",
        actors=["US"],
        assets=["semis"],
        impacted_categories=[],
    )
    assert result == []


def test_actor_matching_is_case_insensitive():
    result = apply_overrides(
        channel="trade",
        actors=["us", "CHINA"],
        assets=["semis"],
        impacted_categories=[],
    )
    assert "Semiconductor Manufacturing" in result


def test_overrides_only_add_never_remove_model_picks():
    result = apply_overrides(
        channel="energy",
        actors=["Saudi Arabia"],
        assets=["crude_oil"],
        impacted_categories=["Energy & Grid Infrastructure"],
    )
    assert "Energy & Grid Infrastructure" in result
    assert len(result) == 1


def test_already_present_category_is_not_duplicated():
    result = apply_overrides(
        channel="conflict",
        actors=["Taiwan"],
        assets=[],
        impacted_categories=["Semiconductor Manufacturing"],
    )
    assert result.count("Semiconductor Manufacturing") == 1


def test_no_rules_triggered_returns_model_picks_unchanged():
    result = apply_overrides(
        channel="energy",
        actors=["Saudi Arabia"],
        assets=["crude_oil"],
        impacted_categories=["Energy & Grid Infrastructure", "Nuclear & Advanced Energy"],
    )
    assert result == ["Energy & Grid Infrastructure", "Nuclear & Advanced Energy"]


def test_none_actors_and_assets_do_not_crash():
    result = apply_overrides(
        channel=None, actors=None, assets=None, impacted_categories=None,
    )
    assert result == []


def test_spec_worked_example_china_live_fire_drills_taiwan():
    # "China conducts live-fire drills encircling Taiwan" - deterministic
    # override expected regardless of what Layer 2 itself returned
    result = apply_overrides(
        channel="conflict",
        actors=["China", "Taiwan"],
        assets=["broad_equities"],
        impacted_categories=[],
    )
    assert set(result) == {
        "Semiconductor Manufacturing",
        "Compute Hardware & Edge Systems",
        "Networking, Optical & Interconnect",
        "Cloud & Compute Platforms",
    }
