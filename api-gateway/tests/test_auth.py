"""Tests for authentication and authorisation enforcement."""
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.responses import Response


async def test_public_login_route_requires_no_auth(client) -> None:
    """POST /auth/login must be reachable without an Authorization header."""
    with patch(
        "routes.proxy_routes.forward_request",
        new_callable=AsyncMock,
        return_value=Response(status_code=200),
    ):
        resp = await client.post("/auth/login")
    assert resp.status_code == 200


async def test_public_register_route_requires_no_auth(client) -> None:
    """POST /auth/register must be reachable without an Authorization header."""
    with patch(
        "routes.proxy_routes.forward_request",
        new_callable=AsyncMock,
        return_value=Response(status_code=200),
    ):
        resp = await client.post("/auth/register")
    assert resp.status_code == 200


async def test_missing_auth_header_returns_401(client) -> None:
    """Absent Authorization header must return 401."""
    resp = await client.get("/news/articles")
    assert resp.status_code == 401


async def test_unknown_token_returns_401(client) -> None:
    """A token rejected by the auth-service must return 401."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        resp = await client.get(
            "/news/articles",
            headers={"Authorization": "Bearer csec_unknowntoken"},
        )
    assert resp.status_code == 401


async def test_user_token_on_admin_route_returns_403(client) -> None:
    """A user-role token must receive 403 on admin-only routes."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "valid": True, "role": "user", "key_id": 2
    }

    with patch(
        "httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        resp = await client.get(
            "/signal/runs",
            headers={"Authorization": "Bearer csec_usertoken"},
        )
    assert resp.status_code == 403


async def test_valid_admin_token_returns_200(client) -> None:
    """A valid admin token must be proxied successfully (200)."""
    auth_mock = MagicMock()
    auth_mock.status_code = 200
    auth_mock.json.return_value = {
        "valid": True, "role": "admin", "key_id": 1
    }

    upstream_response = Response(status_code=200)

    with (
        patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=auth_mock,
        ),
        patch(
            "routes.proxy_routes.forward_request",
            new_callable=AsyncMock,
            return_value=upstream_response,
        ),
    ):
        resp = await client.get(
            "/news/articles",
            headers={"Authorization": "Bearer csec_admintoken"},
        )
    assert resp.status_code == 200


async def test_caller_header_is_propagated_downstream(client) -> None:
    """x-ocn-caller must be sent to upstream with correct base64 JSON."""
    auth_mock = MagicMock()
    auth_mock.status_code = 200
    auth_mock.json.return_value = {
        "valid": True, "role": "admin", "key_id": 1,
    }

    upstream_mock = MagicMock()
    upstream_mock.status_code = 200
    upstream_mock.content = b""
    upstream_mock.headers = {}

    captured: dict = {}

    async def capture_request(**kwargs: object) -> MagicMock:
        captured["headers"] = kwargs.get("headers", {})
        return upstream_mock

    with (
        patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=auth_mock,
        ),
        patch(
            "proxy._client.request",
            new=AsyncMock(side_effect=capture_request),
        ),
    ):
        resp = await client.get(
            "/news/articles",
            headers={"Authorization": "Bearer csec_admintoken"},
        )

    assert resp.status_code == 200
    assert "x-ocn-caller" in captured["headers"]
    payload = json.loads(
        base64.b64decode(captured["headers"]["x-ocn-caller"])
    )
    assert payload == {"sub": 1, "role": "admin", "domains": []}
