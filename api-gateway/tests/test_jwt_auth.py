"""Tests for JWT-based authentication and domain scoping."""
import base64
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.responses import Response

import auth as auth_module

_PRIVATE_KEY = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend(),
)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


def _make_jwt(
    sub: str = "42",
    role: str = "user",
    domains: list[str] | None = None,
    expired: bool = False,
) -> str:
    """Return a signed RS256 JWT for testing."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "domains": domains if domains is not None else [],
        "iat": now,
        "exp": now + (-1 if expired else 3600),
    }
    return jwt.encode(payload, _PRIVATE_KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def reset_cached_key():
    """Ensure the module-level key cache is primed with the test key."""
    original = auth_module._cached_public_key
    auth_module._cached_public_key = _PUBLIC_KEY
    yield
    auth_module._cached_public_key = original


async def test_valid_jwt_accepted(client) -> None:
    """A valid JWT must be accepted on a protected route (200)."""
    token = _make_jwt(role="user", domains=["acme"])
    with patch(
        "routes.proxy_routes.forward_request",
        new_callable=AsyncMock,
        return_value=Response(status_code=200),
    ):
        resp = await client.get(
            "/news/articles",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200


async def test_expired_jwt_returns_401(client) -> None:
    """An expired JWT must return 401."""
    token = _make_jwt(expired=True)
    resp = await client.get(
        "/news/articles",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


async def test_tampered_jwt_returns_401(client) -> None:
    """A JWT with a modified payload must return 401."""
    token = _make_jwt()
    header, payload_b64, signature = token.split(".")
    raw = base64.urlsafe_b64decode(payload_b64 + "==")
    claims = json.loads(raw)
    claims["role"] = "admin"
    tampered_payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode())
        .rstrip(b"=")
        .decode()
    )
    tampered = f"{header}.{tampered_payload}.{signature}"
    resp = await client.get(
        "/news/articles",
        headers={"Authorization": f"Bearer {tampered}"},
    )
    assert resp.status_code == 401


async def test_jwt_domain_not_in_claims_returns_403(client) -> None:
    """A JWT without the requested domain must be rejected 403 on POST /news/run."""
    token = _make_jwt(role="user", domains=["other-domain"])
    resp = await client.post(
        "/news/run",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        content=json.dumps({"domain": "acme"}),
    )
    assert resp.status_code == 403


async def test_admin_jwt_bypasses_domain_scoping(client) -> None:
    """An admin JWT must bypass domain scoping on POST /news/run."""
    token = _make_jwt(role="admin", domains=[])
    with patch(
        "routes.proxy_routes.forward_request",
        new_callable=AsyncMock,
        return_value=Response(status_code=202),
    ):
        resp = await client.post(
            "/news/run",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            content=json.dumps({"domain": "acme"}),
        )
    assert resp.status_code == 202


async def test_jwt_with_matching_domain_proxied(client) -> None:
    """A JWT whose domains include the requested domain must be proxied."""
    token = _make_jwt(role="user", domains=["acme", "beta"])
    with patch(
        "routes.proxy_routes.forward_request",
        new_callable=AsyncMock,
        return_value=Response(status_code=202),
    ):
        resp = await client.post(
            "/news/run",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            content=json.dumps({"domain": "acme"}),
        )
    assert resp.status_code == 202


async def test_x_ocn_caller_populated_from_jwt(client) -> None:
    """x-ocn-caller forwarded downstream must reflect JWT claims."""
    token = _make_jwt(sub="99", role="user", domains=["acme"])

    upstream_mock = MagicMock()
    upstream_mock.status_code = 200
    upstream_mock.content = b""
    upstream_mock.headers = {}

    captured: dict = {}

    async def capture_request(**kwargs: object) -> MagicMock:
        captured["headers"] = kwargs.get("headers", {})
        return upstream_mock

    with patch(
        "proxy._client.request",
        new=AsyncMock(side_effect=capture_request),
    ):
        resp = await client.get(
            "/news/articles",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert "x-ocn-caller" in captured["headers"]
    payload = json.loads(
        base64.b64decode(captured["headers"]["x-ocn-caller"])
    )
    assert payload == {"sub": "99", "role": "user", "domains": ["acme"]}
