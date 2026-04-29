"""Tests for authentication and authorisation enforcement."""
import base64
import json

import pytest


def _ocn_caller(sub: int, role: str, domains: list = None) -> str:
    """Build a valid x-ocn-caller header value."""
    payload = json.dumps(
        {"sub": sub, "role": role, "domains": domains or []}
    )
    return base64.b64encode(payload.encode()).decode()


async def test_missing_caller_header_returns_401(client) -> None:
    """Absent x-ocn-caller header returns 401."""
    resp = await client.get("/domains")
    assert resp.status_code == 401


async def test_malformed_caller_header_returns_401(client) -> None:
    """Garbage in x-ocn-caller returns 401."""
    resp = await client.get(
        "/domains",
        headers={"x-ocn-caller": "not-valid-base64!!!"},
    )
    assert resp.status_code == 401


async def test_valid_caller_header_returns_200(client) -> None:
    """A well-formed x-ocn-caller header allows the request through."""
    resp = await client.get(
        "/domains",
        headers={"x-ocn-caller": _ocn_caller(1, "admin")},
    )
    assert resp.status_code == 200


async def test_user_key_on_admin_endpoint_returns_403(client) -> None:
    """A user-role caller must receive 403 on admin-only endpoints."""
    resp = await client.post(
        "/frequencies",
        json={"name": "test-forbidden-freq", "min_days_back": 99},
        headers={"x-ocn-caller": _ocn_caller(2, "user")},
    )
    assert resp.status_code == 403
