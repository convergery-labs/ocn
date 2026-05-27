"""Unit tests for job-level caching in submit_run."""
import sys
import os
import asyncio
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'src'))

from controllers.run import submit_run


def _run(coro):
    return asyncio.run(coro)


def test_cache_hit_returns_existing_job():
    """Cache hit: completed job exists → return existing job_id, no new job created."""
    with (
        patch('controllers.run.resolve_news_run_id', new=AsyncMock(return_value=42)),
        patch('controllers.run.get_completed_job_for_run', return_value={'id': 99}),
        patch('controllers.run.create_job') as mock_create,
    ):
        job_id, news_run_id, cached = _run(
            submit_run(domain='ai', run_id=None, days_back=7, use_latest_run=False, force=False)
        )

    assert job_id == 99
    assert news_run_id == 42
    assert cached is True
    mock_create.assert_not_called()


def test_cache_miss_creates_new_job():
    """Cache miss: no completed job → create_job is called and its id is returned."""
    with (
        patch('controllers.run.resolve_news_run_id', new=AsyncMock(return_value=42)),
        patch('controllers.run.get_completed_job_for_run', return_value=None),
        patch('controllers.run.create_job', return_value=7) as mock_create,
    ):
        job_id, news_run_id, cached = _run(
            submit_run(domain='ai', run_id=None, days_back=7, use_latest_run=False, force=False)
        )

    assert job_id == 7
    assert news_run_id == 42
    assert cached is False
    mock_create.assert_called_once_with(domain='ai', news_run_id=42)


def test_force_bypasses_cache():
    """force=True: skip cache check even when a completed job exists."""
    with (
        patch('controllers.run.resolve_news_run_id', new=AsyncMock(return_value=42)),
        patch('controllers.run.get_completed_job_for_run') as mock_cache,
        patch('controllers.run.create_job', return_value=55),
    ):
        job_id, news_run_id, cached = _run(
            submit_run(domain='ai', run_id=None, days_back=7, use_latest_run=False, force=True)
        )

    assert job_id == 55
    assert cached is False
    mock_cache.assert_not_called()
