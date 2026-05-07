"""Unit tests for the digest pipeline controller."""
import sys
import os
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _make_classification(url, title, label="Signal", score=0.8):
    return {
        "article_url": url,
        "article_title": title,
        "label": label,
        "composite_score": score,
    }


@patch("adapters.smtp_sender.send_digest")
@patch("adapters.llm_client.summarise_category", return_value="Summary.")
@patch(
    "adapters.llm_client.categorise_articles",
    return_value={
        "AI Core Platforms, Software, and Security": [
            {"url": "http://a.com", "title": "A", "label": "Signal",
             "composite_score": 0.9}
        ]
    },
)
@patch(
    "adapters.signal_client.get_job_results",
    return_value=[_make_classification("http://a.com", "A")],
)
@patch("adapters.signal_client.poll_job_until_done")
@patch("adapters.signal_client.trigger_run", return_value=99)
@patch(
    "adapters.signal_client.get_latest_job",
    return_value=None,
)
def test_run_digest_polling_fresh(
    mock_latest,
    mock_trigger_run,
    mock_poll_job,
    mock_results,
    mock_categorise,
    mock_summarise,
    mock_send,
):
    """Full pipeline runs when no fresh classification exists."""
    from controllers.digest import run_digest_polling

    run_digest_polling()

    mock_trigger_run.assert_called_once_with(domain="ai_news")
    mock_poll_job.assert_called_once_with(99)
    mock_results.assert_called_once_with(99)
    mock_send.assert_called_once()


@patch("adapters.smtp_sender.send_digest")
@patch("adapters.llm_client.summarise_category", return_value="Summary.")
@patch("adapters.llm_client.categorise_articles", return_value={})
@patch("adapters.signal_client.get_job_results", return_value=[])
@patch(
    "adapters.signal_client.get_latest_job",
    return_value={
        "job_id": 5,
        "completed_at": "2099-01-01T12:00:00",
    },
)
def test_run_digest_polling_already_fresh(
    mock_latest,
    mock_results,
    mock_categorise,
    mock_summarise,
    mock_send,
):
    """Pipeline skips trigger when today's classification exists."""
    with patch("controllers.digest._is_today", return_value=True):
        from controllers.digest import run_digest_polling

        run_digest_polling()

    mock_send.assert_called_once()


def test_is_today_true():
    """_is_today returns True for today's date."""
    from datetime import datetime, timezone
    from controllers.digest import _is_today

    now = datetime.now(timezone.utc).isoformat()
    assert _is_today(now) is True


def test_is_today_false_old():
    """_is_today returns False for a past date."""
    from controllers.digest import _is_today

    assert _is_today("2020-01-01T00:00:00") is False


def test_is_today_none():
    """_is_today returns False for None."""
    from controllers.digest import _is_today

    assert _is_today(None) is False
