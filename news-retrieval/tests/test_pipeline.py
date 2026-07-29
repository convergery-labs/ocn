"""Tests for pipeline.py behaviour, specifically fail-open on LLM error."""
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pipeline as pipeline_module
from db import get_db

_GDELT_FIXTURE_SEENDATE = (
    datetime.now(timezone.utc) - timedelta(hours=1)
).strftime("%Y%m%dT%H%M%SZ")

GDELT_RESPONSE_FIXTURE = {
    "articles": [
        {
            "url": "https://example.com/conflict-story",
            "title": "Conflict escalates in region",
            "seendate": _GDELT_FIXTURE_SEENDATE,
            "socialimage": "",
            "domain": "example.com",
            "language": "English",
            "sourcecountry": "Ukraine",
        },
    ],
}


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


def _insert_stored_run_with_article(domain: str, url: str) -> None:
    """Insert a completed run with one article already stored for domain."""
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO runs
                (name, domain, days_back, model,
                 status, completed_at, article_count)
            VALUES
                (?, ?, 7, 'test-model', 'completed', NOW(), 1)
            RETURNING id
            """,
            (f"prior-{domain}", domain),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO articles (run_id, url, title, source)
            VALUES (?, ?, 'Already Seen', 'Test Feed')
            """,
            (row["id"], url),
        )


def test_cross_run_dedup_excludes_previously_stored_url() -> None:
    """An article whose URL is already stored for the domain is dropped
    before it reaches the relevance filter, and never re-inserted."""
    domain = "ai_news"
    seen_url = "http://example.com/already-seen"
    _insert_stored_run_with_article(domain, seen_url)

    seen_entry = types.SimpleNamespace(published_parsed=None)
    seen_entry.get = lambda k, d="": {  # type: ignore[assignment]
        "title": "Already Seen",
        "link": seen_url,
        "published": "2026-01-01",
        "summary": "Summary.",
    }.get(k, d)
    new_entry = types.SimpleNamespace(published_parsed=None)
    new_entry.get = lambda k, d="": {  # type: ignore[assignment]
        "title": "Brand New Article",
        "link": "http://example.com/brand-new",
        "published": "2026-01-01",
        "summary": "Summary.",
    }.get(k, d)
    fake_feed = types.SimpleNamespace(
        entries=[seen_entry, new_entry],
        feed=types.SimpleNamespace(get=lambda k, d="": "Test Feed"),
    )

    mock_client: MagicMock = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(
            content=(
                '{"articles": ['
                f'{{"url": "{seen_url}", "relevant": true}},'
                '{"url": "http://example.com/brand-new",'
                ' "relevant": true}'
                ']}'
            )
        ))]
    )

    with (
        patch("feedparser.parse", return_value=fake_feed),
        patch("pipeline._make_client", return_value=mock_client),
    ):
        result = pipeline_module.run(
            domain_slug=domain,
            domain_name="AI News",
            days_back=7,
            model="test-model",
        )

    urls = {a["url"] for a in result["articles"]}
    assert urls == {"http://example.com/brand-new"}


def test_cross_domain_dedup_excludes_url_stored_under_different_domain() -> None:
    """A URL already stored under a DIFFERENT domain's run is dropped too -
    dedup is global, not scoped to the requesting domain."""
    seen_url = "http://example.com/stored-under-other-domain"
    _insert_stored_run_with_article("smart_money", seen_url)

    seen_entry = types.SimpleNamespace(published_parsed=None)
    seen_entry.get = lambda k, d="": {  # type: ignore[assignment]
        "title": "Already Seen Elsewhere",
        "link": seen_url,
        "published": "2026-01-01",
        "summary": "Summary.",
    }.get(k, d)
    fake_feed = types.SimpleNamespace(
        entries=[seen_entry],
        feed=types.SimpleNamespace(get=lambda k, d="": "Test Feed"),
    )

    mock_client: MagicMock = MagicMock()

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

    assert result["articles"] == []
    mock_client.chat.completions.create.assert_not_called()


def test_fetch_gdelt_parses_doc_response() -> None:
    """_fetch_one_gdelt maps GDELT DOC API fields onto article dicts."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = GDELT_RESPONSE_FIXTURE
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        results = pipeline_module._fetch_one_gdelt(
            "theme:ARMEDCONFLICT sourcelang:english", days_back=1
        )

    assert mock_get.call_args.kwargs["params"]["timespan"] == "1d"
    assert len(results) == 1
    article = results[0]
    assert article["url"] == "https://example.com/conflict-story"
    assert article["title"] == "Conflict escalates in region"
    assert article["source"] == "example.com"
    assert article["summary"] is None
    assert article["body"] is None
    assert article["metadata"]["sourcecountry"] == "Ukraine"
    assert article["_pub_date"] is not None


def test_fetch_one_gdelt_returns_sentinel_on_429_without_retrying() -> None:
    """_fetch_one_gdelt makes exactly one attempt and signals rate-limiting
    via the sentinel - retry/round-robin orchestration lives in
    _fetch_gdelt, not here."""
    rate_limited_resp = MagicMock()
    rate_limited_resp.status_code = 429

    with patch("httpx.get", return_value=rate_limited_resp) as mock_get:
        result = pipeline_module._fetch_one_gdelt(
            "theme:ARMEDCONFLICT sourcelang:english", days_back=1
        )

    assert result is pipeline_module._GDELT_RATE_LIMITED
    assert mock_get.call_count == 1


def test_fetch_gdelt_round_robins_before_retrying_a_rate_limited_query() -> None:
    """A rate-limited query is not retried immediately - _fetch_gdelt moves
    on to the next query first, and only retries it in a later pass."""
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = GDELT_RESPONSE_FIXTURE
    ok_resp.raise_for_status.return_value = None
    rate_limited_resp = MagicMock()
    rate_limited_resp.status_code = 429

    source = {
        "source_type": "gdelt",
        "config": {"queries": ["theme:ARMEDCONFLICT", "theme:TERROR"]},
    }

    # theme:ARMEDCONFLICT: 429 then ok on retry. theme:TERROR: ok first try.
    # Call order proves TERROR (query 2) runs BEFORE ARMEDCONFLICT's retry.
    with (
        patch(
            "httpx.get",
            side_effect=[rate_limited_resp, ok_resp, ok_resp],
        ) as mock_get,
        patch("pipeline.time.sleep"),
    ):
        results = pipeline_module._fetch_gdelt([source], days_back=1)

    assert mock_get.call_count == 3
    first_call_query = mock_get.call_args_list[0].kwargs["params"]["query"]
    second_call_query = mock_get.call_args_list[1].kwargs["params"]["query"]
    assert first_call_query == "theme:ARMEDCONFLICT"
    assert second_call_query == "theme:TERROR"  # moved on, didn't retry immediately
    assert len(results) == 1  # same URL from both queries, deduped


def test_fetch_gdelt_gives_up_after_max_rounds_still_rate_limited() -> None:
    """A query still 429ing after _GDELT_MAX_ROUNDS passes is skipped, not
    retried forever."""
    rate_limited_resp = MagicMock()
    rate_limited_resp.status_code = 429

    source = {
        "source_type": "gdelt",
        "config": {"queries": ["theme:ARMEDCONFLICT"]},
    }

    with (
        patch("httpx.get", return_value=rate_limited_resp) as mock_get,
        patch("pipeline.time.sleep"),
    ):
        results = pipeline_module._fetch_gdelt([source], days_back=1)

    assert results == []
    assert mock_get.call_count == pipeline_module._GDELT_MAX_ROUNDS


def test_fetch_gdelt_dedupes_across_queries_and_paces_requests() -> None:
    """_fetch_gdelt dedupes by URL across theme queries and sleeps between calls."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = GDELT_RESPONSE_FIXTURE
    mock_resp.raise_for_status.return_value = None

    source = {
        "source_type": "gdelt",
        "config": {"queries": ["theme:ARMEDCONFLICT", "theme:TERROR"]},
    }

    with (
        patch("httpx.get", return_value=mock_resp) as mock_get,
        patch("pipeline.time.sleep") as mock_sleep,
        patch("trafilatura.fetch_url", return_value="<html>page</html>"),
        patch("trafilatura.extract", return_value="Extracted body text."),
    ):
        results = pipeline_module._fetch_gdelt([source], days_back=1)

    assert len(results) == 1  # same URL returned by both queries, deduped
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once()  # spacing enforced between the two queries
    assert results[0]["body"] == "Extracted body text."


def test_fetch_gdelt_body_none_when_extraction_fails() -> None:
    """_fetch_gdelt leaves body as None when Trafilatura can't fetch the page."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = GDELT_RESPONSE_FIXTURE
    mock_resp.raise_for_status.return_value = None

    source = {
        "source_type": "gdelt",
        "config": {"queries": ["theme:ARMEDCONFLICT"]},
    }

    with (
        patch("httpx.get", return_value=mock_resp),
        patch("pipeline.time.sleep"),
        patch("trafilatura.fetch_url", return_value=None),
    ):
        results = pipeline_module._fetch_gdelt([source], days_back=1)

    assert len(results) == 1
    assert results[0]["body"] is None


def test_fetch_gdelt_skips_body_fetch_for_already_stored_urls() -> None:
    """_fetch_gdelt drops globally-already-stored URLs before body-fetch."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = GDELT_RESPONSE_FIXTURE
    mock_resp.raise_for_status.return_value = None

    source = {
        "source_type": "gdelt",
        "config": {"queries": ["theme:ARMEDCONFLICT"]},
    }

    with (
        patch("httpx.get", return_value=mock_resp),
        patch("pipeline.time.sleep"),
        patch(
            "pipeline.get_already_stored_urls",
            return_value={"https://example.com/conflict-story"},
        ) as mock_lookup,
        patch("trafilatura.fetch_url") as mock_fetch_url,
    ):
        results = pipeline_module._fetch_gdelt([source], days_back=1)

    assert results == []
    mock_fetch_url.assert_not_called()  # no body fetch wasted on a stored URL
    mock_lookup.assert_called_once_with(
        ["https://example.com/conflict-story"]
    )


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
