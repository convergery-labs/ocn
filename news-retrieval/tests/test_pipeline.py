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


def _make_entry(*, content_words: int = 0) -> types.SimpleNamespace:
    """Return a fake feedparser entry for pipeline tests.

    Args:
        content_words: Number of words in the ``content:encoded`` value.
            0 means content:encoded is absent.
    """
    body_text = " ".join(["word"] * content_words)
    content_list = (
        [{"value": body_text, "type": "text/html"}]
        if content_words > 0
        else []
    )
    entry = types.SimpleNamespace(published_parsed=None)
    data = {
        "title": "Test Article",
        "link": "http://example.com/test",
        "published": "2026-01-01",
        "summary": "Short summary.",
        "content": content_list,
    }
    entry.get = lambda k, d="": data.get(k, d)  # type: ignore[assignment]
    return entry


def _fake_pipeline_run(
    source: dict,
    *,
    content_words: int = 0,
    mock_client: MagicMock,
    trafilatura_patches: dict | None = None,
) -> dict:
    """Run the pipeline with a controlled source and feed entry.

    Args:
        source: Source dict with ``url`` and ``no_fetch`` keys.
        content_words: Words in the ``content:encoded`` value; 0 = absent.
        mock_client: Pre-configured mock LLM client.
        trafilatura_patches: Optional dict mapping
            ``"fetch_url"`` / ``"extract"`` to return values.

    Returns:
        pipeline.run result dict.
    """
    entry = _make_entry(content_words=content_words)
    fake_feed = types.SimpleNamespace(
        entries=[entry],
        feed=types.SimpleNamespace(get=lambda k, d="": "Test Feed"),
    )
    patches: list = [
        patch("feedparser.parse", return_value=fake_feed),
        patch("pipeline._make_client", return_value=mock_client),
        patch(
            "pipeline.load_sources",
            return_value=[source],
        ),
    ]
    tf = trafilatura_patches or {}
    fetch_patch = patch(
        "trafilatura.fetch_url",
        return_value=tf.get("fetch_url"),
    )
    extract_patch = patch(
        "trafilatura.extract",
        return_value=tf.get("extract"),
    )
    with fetch_patch as mock_fetch, extract_patch as mock_extract:
        with patches[0], patches[1], patches[2]:
            result = pipeline_module.run(
                domain_slug="ai_news",
                domain_name="AI News",
                days_back=7,
                model="test-model",
            )
    return result, mock_fetch, mock_extract


def test_body_from_content_encoded() -> None:
    """body is populated from content:encoded when it has ≥ 150 words."""
    source = {
        "url": "http://example.com/feed",
        "min_days_back": 1,
        "no_fetch": False,
    }
    mock_client: MagicMock = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(
            content='{"articles": [{"url": "http://example.com/test",'
                    ' "relevant": true}]}'
        ))]
    )

    result, mock_fetch, _ = _fake_pipeline_run(
        source, content_words=150, mock_client=mock_client
    )

    assert len(result["articles"]) == 1
    body = result["articles"][0]["body"]
    assert body is not None
    assert len(body.split()) >= 150
    mock_fetch.assert_not_called()


def test_body_trafilatura_fallback() -> None:
    """body is populated via Trafilatura when content:encoded is absent."""
    source = {
        "url": "http://example.com/feed",
        "min_days_back": 1,
        "no_fetch": False,
    }
    mock_client: MagicMock = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(
            content='{"articles": [{"url": "http://example.com/test",'
                    ' "relevant": true}]}'
        ))]
    )
    trafilatura_body = "Extracted article body text from Trafilatura."

    result, mock_fetch, mock_extract = _fake_pipeline_run(
        source,
        content_words=0,
        mock_client=mock_client,
        trafilatura_patches={
            "fetch_url": "<html>page</html>",
            "extract": trafilatura_body,
        },
    )

    assert len(result["articles"]) == 1
    assert result["articles"][0]["body"] == trafilatura_body
    mock_fetch.assert_called_once_with("http://example.com/test")


def test_body_null_for_no_fetch_source() -> None:
    """body is None and Trafilatura is not called for no_fetch sources."""
    source = {
        "url": "http://example.com/feed",
        "min_days_back": 1,
        "no_fetch": True,
    }
    mock_client: MagicMock = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(
            content='{"articles": [{"url": "http://example.com/test",'
                    ' "relevant": true}]}'
        ))]
    )

    result, mock_fetch, mock_extract = _fake_pipeline_run(
        source, content_words=0, mock_client=mock_client
    )

    assert len(result["articles"]) == 1
    assert result["articles"][0]["body"] is None
    mock_fetch.assert_not_called()
    mock_extract.assert_not_called()
