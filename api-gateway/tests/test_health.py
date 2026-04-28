"""Tests for GET /health."""
import os

import pytest


async def test_health_returns_200_when_all_urls_set(client) -> None:
    """GET /health returns 200 when all GATEWAY_* vars are configured."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_returns_503_when_url_missing(client) -> None:
    """GET /health returns 503 when a required env var is absent."""
    original = os.environ.pop("GATEWAY_AUTH_URL", None)
    try:
        resp = await client.get("/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["checks"]["GATEWAY_AUTH_URL"] is False
    finally:
        if original is not None:
            os.environ["GATEWAY_AUTH_URL"] = original
