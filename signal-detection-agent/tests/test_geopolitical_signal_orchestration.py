"""Unit tests for run_geopolitical_signal_stage_a orchestration
(fetch -> skip-check -> Stage A -> insert)."""
import sys
import os
import asyncio
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'src'))

from controllers.run import run_geopolitical_signal_stage_a


def _run(coro):
    return asyncio.run(coro)


def _article(id, title, source="reuters.com", url=None, language="English"):
    return {
        "id": id,
        "title": title,
        "source": source,
        "url": url or f"https://{source}/{id}",
        "published": "2026-09-08T06:40:00+00:00",
        "metadata": {"language": language},
    }


def test_pools_articles_across_multiple_runs_and_dedupes_by_url():
    articles_by_run = {
        1: [_article(1, "Iran closes the Strait of Hormuz")],
        2: [
            _article(1, "Iran closes the Strait of Hormuz"),  # same url as run 1 - deduped
            _article(2, "China bans gallium exports"),
        ],
    }

    async def fake_get_run_articles(run_id):
        return articles_by_run[run_id]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.list_completed_runs', new=AsyncMock(return_value=[1, 2])),
        patch('controllers.run.get_run_articles', new=AsyncMock(side_effect=fake_get_run_articles)),
        patch('controllers.run.get_existing_geopolitical_signal_article_ids', return_value=set()),
        patch('controllers.run.insert_geopolitical_signal_classification') as mock_insert,
    ):
        _run(run_geopolitical_signal_stage_a(job_id=1, from_date="2026-09-08", to_date="2026-09-08"))

    # 2 distinct articles after URL dedup (article id=1 appears in both runs, same url)
    assert mock_insert.call_count == 2
    inserted_ids = {call.args[1]["id"] for call in mock_insert.call_args_list}
    assert inserted_ids == {1, 2}


def test_skips_already_classified_articles():
    async def fake_get_run_articles(run_id):
        return [_article(1, "Iran closes the Strait of Hormuz"), _article(2, "China bans gallium exports")]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.list_completed_runs', new=AsyncMock(return_value=[1])),
        patch('controllers.run.get_run_articles', new=AsyncMock(side_effect=fake_get_run_articles)),
        patch('controllers.run.get_existing_geopolitical_signal_article_ids', return_value={1}),
        patch('controllers.run.insert_geopolitical_signal_classification') as mock_insert,
    ):
        _run(run_geopolitical_signal_stage_a(job_id=1, from_date="2026-09-08", to_date="2026-09-08"))

    # article id=1 already classified -> skipped; only id=2 gets inserted
    assert mock_insert.call_count == 1
    assert mock_insert.call_args.args[1]["id"] == 2


def test_writes_correct_outcome_per_article():
    async def fake_get_run_articles(run_id):
        return [
            _article(1, "Iran warns it may close the Strait of Hormuz"),  # WEAK
            _article(2, "Iran closes the Strait of Hormuz"),  # WAITING
            _article(3, "Ukraine reshuffles leadership", source="orissapost.com"),  # DROPPED
        ]

    with (
        patch('controllers.run.update_job_status'),
        patch('controllers.run.list_completed_runs', new=AsyncMock(return_value=[1])),
        patch('controllers.run.get_run_articles', new=AsyncMock(side_effect=fake_get_run_articles)),
        patch('controllers.run.get_existing_geopolitical_signal_article_ids', return_value=set()),
        patch('controllers.run.insert_geopolitical_signal_classification') as mock_insert,
    ):
        _run(run_geopolitical_signal_stage_a(job_id=1, from_date="2026-09-08", to_date="2026-09-08"))

    results_by_id = {call.args[1]["id"]: call.args[2] for call in mock_insert.call_args_list}
    assert results_by_id[1]["outcome"] == "WEAK"
    assert results_by_id[2]["outcome"] == "WAITING"
    assert results_by_id[3] == {"outcome": "DROPPED", "drop_reason": "domain_not_allowed"}


def test_no_articles_marks_job_completed_with_zero_count():
    with (
        patch('controllers.run.update_job_status') as mock_status,
        patch('controllers.run.list_completed_runs', new=AsyncMock(return_value=[])),
        patch('controllers.run.insert_geopolitical_signal_classification') as mock_insert,
    ):
        _run(run_geopolitical_signal_stage_a(job_id=1, from_date="2026-09-08", to_date="2026-09-08"))

    mock_insert.assert_not_called()
    mock_status.assert_any_call(1, "completed", article_count=0, set_completed_at=True)


def test_fetch_failure_marks_job_failed():
    from adapters.news_client import NewsRetrievalError

    with (
        patch('controllers.run.update_job_status') as mock_status,
        patch('controllers.run.list_completed_runs', new=AsyncMock(side_effect=NewsRetrievalError("boom"))),
        patch('controllers.run.insert_geopolitical_signal_classification') as mock_insert,
    ):
        _run(run_geopolitical_signal_stage_a(job_id=1, from_date="2026-09-08", to_date="2026-09-08"))

    mock_insert.assert_not_called()
    mock_status.assert_any_call(1, "failed", set_completed_at=True)
