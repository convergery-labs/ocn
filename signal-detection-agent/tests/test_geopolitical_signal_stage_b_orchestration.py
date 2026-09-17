"""Unit tests for run_geopolitical_signal_stage_b orchestration
(worklist -> daily cap -> classify -> update in place)."""
import sys
import os
import asyncio
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'src'))

from controllers.run import run_geopolitical_signal_stage_b


def _run(coro):
    return asyncio.run(coro)


def _row(id, article_id, title):
    return {"id": id, "article_id": article_id, "title": title}


def test_no_waiting_rows_marks_job_completed_with_zero_count():
    with (
        patch('controllers.run.update_job_status') as mock_status,
        patch('controllers.run.get_waiting_geopolitical_signal_articles', return_value=[]),
        patch('controllers.run.update_geopolitical_signal_classification') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_b(job_id=1))

    mock_update.assert_not_called()
    mock_status.assert_any_call(1, "completed", article_count=0, set_completed_at=True)


def test_classifies_all_waiting_rows_under_cap():
    rows = [_row(1, 101, "Iran closes the Strait of Hormuz"), _row(2, 102, "China bans gallium exports")]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_waiting_geopolitical_signal_articles', return_value=rows),
        patch('controllers.run.count_geopolitical_signal_stage_b_calls_today', return_value=0),
        patch('controllers.run.load_stage_b_prompt', return_value="prompt"),
        patch('controllers.run.classify_geopolitical_signal_headline', side_effect=["HIGH", "WEAK"]),
        patch('controllers.run.update_geopolitical_signal_classification') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_b(job_id=1))

    assert mock_update.call_count == 2
    mock_update.assert_any_call(1, outcome="HIGH")
    mock_update.assert_any_call(2, outcome="WEAK")


def test_daily_cap_limits_how_many_are_classified():
    rows = [_row(i, 100 + i, f"Headline {i}") for i in range(5)]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_waiting_geopolitical_signal_articles', return_value=rows),
        # already_today=997, cap=1000 (config default) -> only 3 remaining slots
        patch('controllers.run.count_geopolitical_signal_stage_b_calls_today', return_value=997),
        patch('controllers.run.load_stage_b_prompt', return_value="prompt"),
        patch('controllers.run.classify_geopolitical_signal_headline', return_value="WEAK"),
        patch('controllers.run.update_geopolitical_signal_classification') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_b(job_id=1))

    # only 3 of the 5 waiting rows should have been classified/updated
    assert mock_update.call_count == 3


def test_cap_already_exhausted_classifies_nothing():
    rows = [_row(1, 101, "Iran closes the Strait of Hormuz")]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_waiting_geopolitical_signal_articles', return_value=rows),
        patch('controllers.run.count_geopolitical_signal_stage_b_calls_today', return_value=1000),
        patch('controllers.run.load_stage_b_prompt', return_value="prompt"),
        patch('controllers.run.classify_geopolitical_signal_headline') as mock_classify,
        patch('controllers.run.update_geopolitical_signal_classification') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_b(job_id=1))

    mock_classify.assert_not_called()
    mock_update.assert_not_called()


def test_update_failure_does_not_stop_remaining_rows():
    rows = [_row(1, 101, "A"), _row(2, 102, "B")]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_waiting_geopolitical_signal_articles', return_value=rows),
        patch('controllers.run.count_geopolitical_signal_stage_b_calls_today', return_value=0),
        patch('controllers.run.load_stage_b_prompt', return_value="prompt"),
        patch('controllers.run.classify_geopolitical_signal_headline', return_value="WEAK"),
        patch(
            'controllers.run.update_geopolitical_signal_classification',
            side_effect=[Exception("db error"), None],
        ) as mock_update,
    ):
        _run(run_geopolitical_signal_stage_b(job_id=1))

    # both rows attempted despite the first raising
    assert mock_update.call_count == 2
