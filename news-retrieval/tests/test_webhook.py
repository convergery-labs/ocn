"""Tests for webhook delivery on run completion and failure."""
from unittest.mock import MagicMock, patch


async def test_webhook_fires_on_completion(
    client, admin_key, mock_pipeline
) -> None:
    """callback_url receives a POST with status=completed on success."""
    cb = "http://hook.test/completed"
    mock_post = MagicMock()

    with patch("httpx.post", mock_post):
        resp = await client.post(
            "/run",
            json={"domain": "ai_news", "callback_url": cb},
            headers={"x-ocn-caller": admin_key},
        )

    assert resp.status_code == 202
    mock_post.assert_called_once()
    url = mock_post.call_args.args[0]
    payload = mock_post.call_args.kwargs["json"]
    assert url == cb
    assert payload["status"] == "completed"
    assert payload["domain"] == "ai_news"


async def test_webhook_fires_on_failure(
    client, admin_key
) -> None:
    """callback_url receives a POST with status=failed on pipeline error."""
    cb = "http://hook.test/failed"
    mock_post = MagicMock()

    with (
        patch(
            "pipeline.run",
            side_effect=Exception("Simulated pipeline failure"),
        ),
        patch("httpx.post", mock_post),
    ):
        resp = await client.post(
            "/run",
            json={"domain": "ai_news", "callback_url": cb},
            headers={"x-ocn-caller": admin_key},
        )

    assert resp.status_code == 202
    mock_post.assert_called_once()
    payload = mock_post.call_args.kwargs["json"]
    assert payload["status"] == "failed"
    assert payload["domain"] == "ai_news"
