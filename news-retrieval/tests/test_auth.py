"""Tests for authentication and authorisation enforcement."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


async def test_missing_auth_header_returns_422(client) -> None:
    """Absent Authorization header returns 422 (required field)."""
    resp = await client.get("/domains")
    assert resp.status_code == 422


async def test_unknown_bearer_token_returns_401(client) -> None:
    """An unrecognised Bearer token must return 401."""
    resp = await client.get(
        "/domains",
        headers={"Authorization": "Bearer unknown_token"},
    )
    assert resp.status_code == 401


async def test_malformed_auth_scheme_returns_401(client) -> None:
    """A non-Bearer Authorization value must return 401."""
    resp = await client.get(
        "/domains",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert resp.status_code == 401


async def test_user_key_on_admin_endpoint_returns_403(
    client, user_key
) -> None:
    """A user-role caller must receive 403 on admin-only endpoints."""
    key, _ = user_key
    resp = await client.post(
        "/frequencies",
        json={"name": "test-forbidden-freq", "min_days_back": 99},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Delegated auth path (AUTH_SERVICE_URL set)
# ---------------------------------------------------------------------------


@pytest.fixture
def with_auth_service_url(monkeypatch):
    """Set AUTH_SERVICE_URL for the duration of a test."""
    monkeypatch.setenv("AUTH_SERVICE_URL", "http://auth-service:8001")
    yield
    monkeypatch.delenv("AUTH_SERVICE_URL", raising=False)


async def test_delegated_valid_key_returns_200(
    real_auth_client, with_auth_service_url
) -> None:
    """A valid key accepted by auth-service allows the request through."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "valid": True, "role": "admin", "key_id": 1
    }

    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        resp = await real_auth_client.get(
            "/domains",
            headers={"Authorization": "Bearer csec_somekey"},
        )
    assert resp.status_code == 200


async def test_delegated_invalid_key_returns_401(
    real_auth_client, with_auth_service_url
) -> None:
    """A key rejected by auth-service (401) propagates as 401."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        resp = await real_auth_client.get(
            "/domains",
            headers={"Authorization": "Bearer csec_badkey"},
        )
    assert resp.status_code == 401


async def test_no_auth_service_url_returns_503(
    real_auth_client,
) -> None:
    """When AUTH_SERVICE_URL is not configured, returns 503."""
    resp = await real_auth_client.get(
        "/domains",
        headers={"Authorization": "Bearer any_token"},
    )
    assert resp.status_code == 503
