"""Shared test fixtures for lucky-clarke."""
import sys
import os

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app import create_app


@pytest.fixture
def app():
    """Return the FastAPI app."""
    return create_app()


@pytest.fixture
async def client(app):
    """Return an AsyncClient wired to the test app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
