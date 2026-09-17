"""Unit tests for run_geopolitical_signal_stage_d orchestration
(fetch also_reported_by from news-retrieval -> grade -> update in place)."""
import sys
import os
import asyncio
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'src'))

from controllers.run import run_geopolitical_signal_stage_d


def _run(coro):
    return asyncio.run(coro)


def _row(id, article_id, title, url, impacted_companies_direct=None):
    return {
        "id": id, "article_id": article_id, "title": title, "url": url,
        "impacted_companies_direct": impacted_companies_direct,
    }


_SOME_GRADE = {
    "grade": "STRONG", "corroborated": False,
    "primary_source": True, "specific": True,
}


def test_no_ungraded_rows_marks_job_completed_with_zero_count():
    with (
        patch('controllers.run.update_job_status') as mock_status,
        patch('controllers.run.get_ungraded_geopolitical_signal_tagged_articles', return_value=[]),
        patch('controllers.run.update_geopolitical_signal_stage_d_grade') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_d(job_id=1))

    mock_update.assert_not_called()
    mock_status.assert_any_call(1, "completed", article_count=0, set_completed_at=True)


def test_full_flow_fetches_article_and_grades_and_updates():
    rows = [_row(1, 101, "US sanctions Iran, 20 vessels", "https://www.reuters.com/x")]
    article = {"metadata": {"also_reported_by": ["apnews.com"]}}

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_ungraded_geopolitical_signal_tagged_articles', return_value=rows),
        patch('controllers.run.get_article', new=AsyncMock(return_value=article)),
        patch('controllers.run.grade_geopolitical_signal_article', return_value=_SOME_GRADE) as mock_grade,
        patch('controllers.run.update_geopolitical_signal_stage_d_grade') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_d(job_id=1))

    mock_grade.assert_called_once_with(
        url="https://www.reuters.com/x",
        title="US sanctions Iran, 20 vessels",
        also_reported_by=["apnews.com"],
        impacted_companies_direct=None,
    )
    mock_update.assert_called_once_with(1, grade_fields=_SOME_GRADE)


def test_missing_article_passes_none_also_reported_by_not_raise():
    rows = [_row(1, 101, "Some headline", "https://www.reuters.com/x")]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_ungraded_geopolitical_signal_tagged_articles', return_value=rows),
        patch('controllers.run.get_article', new=AsyncMock(return_value=None)),
        patch('controllers.run.grade_geopolitical_signal_article', return_value=_SOME_GRADE) as mock_grade,
        patch('controllers.run.update_geopolitical_signal_stage_d_grade') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_d(job_id=1))

    mock_grade.assert_called_once_with(
        url="https://www.reuters.com/x",
        title="Some headline",
        also_reported_by=None,
        impacted_companies_direct=None,
    )
    mock_update.assert_called_once()


def test_impacted_companies_direct_passed_through_from_row():
    rows = [_row(1, 101, "Some headline", "https://www.reuters.com/x", impacted_companies_direct=["NVDA"])]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_ungraded_geopolitical_signal_tagged_articles', return_value=rows),
        patch('controllers.run.get_article', new=AsyncMock(return_value=None)),
        patch('controllers.run.grade_geopolitical_signal_article', return_value=_SOME_GRADE) as mock_grade,
        patch('controllers.run.update_geopolitical_signal_stage_d_grade'),
    ):
        _run(run_geopolitical_signal_stage_d(job_id=1))

    assert mock_grade.call_args.kwargs["impacted_companies_direct"] == ["NVDA"]


def test_update_failure_does_not_stop_remaining_rows():
    rows = [
        _row(1, 101, "A", "https://www.reuters.com/a"),
        _row(2, 102, "B", "https://www.reuters.com/b"),
    ]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_ungraded_geopolitical_signal_tagged_articles', return_value=rows),
        patch('controllers.run.get_article', new=AsyncMock(return_value=None)),
        patch('controllers.run.grade_geopolitical_signal_article', return_value=_SOME_GRADE),
        patch(
            'controllers.run.update_geopolitical_signal_stage_d_grade',
            side_effect=[Exception("db error"), None],
        ) as mock_update,
    ):
        _run(run_geopolitical_signal_stage_d(job_id=1))

    assert mock_update.call_count == 2


def test_no_daily_cap_all_rows_processed():
    # unlike Stage B/C, Stage D has no daily cap - confirm many rows all
    # get processed in one run
    rows = [_row(i, 100 + i, f"Headline {i}", "https://www.reuters.com/x") for i in range(10)]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.get_ungraded_geopolitical_signal_tagged_articles', return_value=rows),
        patch('controllers.run.get_article', new=AsyncMock(return_value=None)),
        patch('controllers.run.grade_geopolitical_signal_article', return_value=_SOME_GRADE),
        patch('controllers.run.update_geopolitical_signal_stage_d_grade') as mock_update,
    ):
        _run(run_geopolitical_signal_stage_d(job_id=1))

    assert mock_update.call_count == 10
