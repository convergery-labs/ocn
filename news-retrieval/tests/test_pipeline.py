"""Tests for pipeline.py behaviour, specifically fail-open on LLM error."""
import types
from unittest.mock import MagicMock, patch

import pipeline as pipeline_module


def test_llm_batch_error_keeps_all_articles() -> None:
    """LLM API error on a batch keeps all articles (fail-open)."""
    entry = types.SimpleNamespace(published_parsed=None)
    entry.get = lambda k, d="": {  # type: ignore[assignment]
        "title": "Fail-open Article",
        "link": "http://example.com/fail-open",
        "published": "2026-01-01",
        "summary": "Summary.",
    }.get(k, d)
    fake_feed = types.SimpleNamespace(
        entries=[entry],
        feed=types.SimpleNamespace(
            get=lambda k, d="": "Test Feed"
        ),
    )
    mock_client: MagicMock = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception(
        "Simulated LLM timeout"
    )

    with (
        patch("feedparser.parse", return_value=fake_feed),
        patch("pipeline._make_client", return_value=mock_client),
    ):
        result = pipeline_module.run(
            domain_slug="ai_news",
            domain_name="AI News",
            days_back=7,
            model="test-model",
        )

    assert len(result["articles"]) > 0
