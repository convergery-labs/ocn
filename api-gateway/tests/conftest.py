"""Shared pytest fixtures for the api-gateway test suite."""
import os
import sys

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "src"),
)

os.environ.setdefault("GATEWAY_AUTH_URL", "http://auth-service:8001")
os.environ.setdefault("GATEWAY_NEWS_URL", "http://news-retrieval:8000")
os.environ.setdefault("GATEWAY_SIGNAL_URL", "http://signal-detection:8002")

from app import create_app  # noqa: E402


@pytest.fixture
async def client() -> AsyncClient:
    """Return an async HTTP test client backed by the ASGI app."""
    application = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as c:
        yield c
