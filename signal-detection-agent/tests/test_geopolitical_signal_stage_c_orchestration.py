"""Unit tests for run_geopolitical_signal_stage_c orchestration
(Layer 1 -> Layer 2 -> overrides -> Layer 3 -> update in place)."""
import sys
import os
import asyncio
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'src'))

from controllers.run import run_geopolitical_signal_stage_c


def _run(coro):
    return asyncio.run(coro)


def _row(id, article_id, title):
    return {"id": id, "article_id": article_id, "title": title}


_EMPTY_LAYER2 = {
    "channel": None, "actors": None, "assets": None,
    "impacted_categories": None, "one_line": None,
}


def test_no_untagged_rows_marks_job_completed_with_zero_count():
    with (
        patch('controllers.run.update_job_status') as mock_status,
        patch('controllers.run.get_untagged_geopolitical_signal_high_articles', return_value=[]),
        patch('controllers.run.update_geopolitical_signal_stage_c_tags') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_c(job_id=1))

    mock_update.assert_not_called()
    mock_status.assert_any_call(1, "completed", article_count=0, set_completed_at=True)


def test_full_flow_combines_all_layers():
    rows = [_row(1, 101, "US announces new export controls on chips to China")]
    layer2_result = {
        "channel": "trade", "actors": ["US", "China"], "assets": ["semis"],
        "impacted_categories": ["Semiconductor Manufacturing"],
        "one_line": "US imposes export controls.",
    }

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_untagged_geopolitical_signal_high_articles', return_value=rows),
        patch('controllers.run.count_geopolitical_signal_stage_c_calls_today', return_value=0),
        patch('controllers.run.get_companies_for_name_matching', return_value=[]),
        patch('controllers.run.find_direct_company_matches', return_value=["NVDA"]),
        patch('controllers.run.classify_geopolitical_signal_tags', return_value=layer2_result),
        patch('controllers.run.apply_overrides', return_value=["Semiconductor Manufacturing"]),
        patch(
            'controllers.run.get_tickers_for_categories',
            return_value={"Semiconductor Manufacturing": ["AMD", "TSM"]},
        ),
        patch('controllers.run.update_geopolitical_signal_stage_c_tags') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_c(job_id=1))

    mock_update.assert_called_once()
    call_args = mock_update.call_args
    assert call_args.args[0] == 1  # row id
    tags = call_args.kwargs["tags"]
    assert tags["channel"] == "trade"
    assert tags["impacted_companies_direct"] == ["NVDA"]
    assert set(tags["impacted_companies_by_category"]) == {"AMD", "TSM"}
    assert tags["impacted_categories"] == ["Semiconductor Manufacturing"]


def test_layer2_failure_still_writes_row_with_null_tags():
    rows = [_row(1, 101, "Some headline")]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_untagged_geopolitical_signal_high_articles', return_value=rows),
        patch('controllers.run.count_geopolitical_signal_stage_c_calls_today', return_value=0),
        patch('controllers.run.get_companies_for_name_matching', return_value=[]),
        patch('controllers.run.find_direct_company_matches', return_value=[]),
        patch('controllers.run.classify_geopolitical_signal_tags', return_value=dict(_EMPTY_LAYER2)),
        patch('controllers.run.apply_overrides', return_value=[]),
        patch('controllers.run.get_tickers_for_categories', return_value={}),
        patch('controllers.run.update_geopolitical_signal_stage_c_tags') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_c(job_id=1))

    # still updated (fail-open, per spec: HIGH with null tags, not dropped)
    mock_update.assert_called_once()
    tags = mock_update.call_args.kwargs["tags"]
    assert tags["channel"] is None
    assert tags["impacted_companies_direct"] is None


def test_daily_cap_limits_how_many_are_classified():
    rows = [_row(i, 100 + i, f"Headline {i}") for i in range(5)]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_untagged_geopolitical_signal_high_articles', return_value=rows),
        # already_today=48, cap=50 (config default) -> only 2 remaining slots
        patch('controllers.run.count_geopolitical_signal_stage_c_calls_today', return_value=48),
        patch('controllers.run.get_companies_for_name_matching', return_value=[]),
        patch('controllers.run.find_direct_company_matches', return_value=[]),
        patch('controllers.run.classify_geopolitical_signal_tags', return_value=dict(_EMPTY_LAYER2)),
        patch('controllers.run.apply_overrides', return_value=[]),
        patch('controllers.run.get_tickers_for_categories', return_value={}),
        patch('controllers.run.update_geopolitical_signal_stage_c_tags') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_c(job_id=1))

    assert mock_update.call_count == 2


def test_cap_already_exhausted_classifies_nothing():
    rows = [_row(1, 101, "Some headline")]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_untagged_geopolitical_signal_high_articles', return_value=rows),
        patch('controllers.run.count_geopolitical_signal_stage_c_calls_today', return_value=50),
        patch('controllers.run.get_companies_for_name_matching', return_value=[]),
        patch('controllers.run.classify_geopolitical_signal_tags') as mock_classify,
        patch('controllers.run.update_geopolitical_signal_stage_c_tags') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_c(job_id=1))

    mock_classify.assert_not_called()
    mock_update.assert_not_called()


def test_company_list_loaded_once_not_per_article():
    rows = [_row(1, 101, "A"), _row(2, 102, "B"), _row(3, 103, "C")]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_untagged_geopolitical_signal_high_articles', return_value=rows),
        patch('controllers.run.count_geopolitical_signal_stage_c_calls_today', return_value=0),
        patch('controllers.run.get_companies_for_name_matching', return_value=[]) as mock_get_companies,
        patch('controllers.run.find_direct_company_matches', return_value=[]),
        patch('controllers.run.classify_geopolitical_signal_tags', return_value=dict(_EMPTY_LAYER2)),
        patch('controllers.run.apply_overrides', return_value=[]),
        patch('controllers.run.get_tickers_for_categories', return_value={}),
        patch('controllers.run.update_geopolitical_signal_stage_c_tags'),
    ):
        _run(run_geopolitical_signal_stage_c(job_id=1))

    # loaded once for the whole run, not once per article (3 articles above)
    assert mock_get_companies.call_count == 1


def test_update_failure_does_not_stop_remaining_rows():
    rows = [_row(1, 101, "A"), _row(2, 102, "B")]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_untagged_geopolitical_signal_high_articles', return_value=rows),
        patch('controllers.run.count_geopolitical_signal_stage_c_calls_today', return_value=0),
        patch('controllers.run.get_companies_for_name_matching', return_value=[]),
        patch('controllers.run.find_direct_company_matches', return_value=[]),
        patch('controllers.run.classify_geopolitical_signal_tags', return_value=dict(_EMPTY_LAYER2)),
        patch('controllers.run.apply_overrides', return_value=[]),
        patch('controllers.run.get_tickers_for_categories', return_value={}),
        patch(
            'controllers.run.update_geopolitical_signal_stage_c_tags',
            side_effect=[Exception("db error"), None],
        ) as mock_update,
    ):
        _run(run_geopolitical_signal_stage_c(job_id=1))

    assert mock_update.call_count == 2
