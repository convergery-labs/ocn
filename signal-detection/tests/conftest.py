"""Pytest fixtures for the signal-detection test suite."""
import os
import sys

import psycopg2
import psycopg2.errors
import pytest
from fastapi import Header, HTTPException
from httpx import ASGITransport, AsyncClient

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "src"),
)

os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5435")
os.environ["POSTGRES_DB"] = "signal-detection-test"
os.environ.setdefault("POSTGRES_USER", "signal-detection")
os.environ.setdefault("POSTGRES_PASSWORD", "signal-detection")
os.environ.setdefault("AUTH_SERVICE_URL", "http://auth-service:8001")
os.environ.setdefault(
    "NEWS_RETRIEVAL_URL", "http://news-retrieval:8000"
)

from app import create_app  # noqa: E402
from auth import require_auth  # noqa: E402
from db import get_db, init_db  # noqa: E402
from seed import seed  # noqa: E402

_CALLERS: dict[str, dict] = {}


async def _auth_override(
    authorization: str = Header(...),
) -> dict:
    """Auth dependency override for tests."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header.",
        )
    token = authorization[len("Bearer "):]
    if token not in _CALLERS:
        raise HTTPException(
            status_code=401,
            detail="Invalid or unknown API key.",
        )
    return _CALLERS[token]


def _create_test_db() -> None:
    """Create the signal-detection-test database if absent."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    user = os.environ.get("POSTGRES_USER", "signal-detection")
    pw = os.environ.get("POSTGRES_PASSWORD", "signal-detection")
    conn = psycopg2.connect(
        host=host, port=port,
        dbname="postgres", user=user, password=pw,
    )
    conn.autocommit = True
    try:
        conn.cursor().execute(
            'CREATE DATABASE "signal-detection-test"'
        )
    except psycopg2.errors.DuplicateDatabase:
        pass
    finally:
        conn.close()


def _wipe_schema() -> None:
    """Drop and recreate the public schema in the test DB."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    user = os.environ.get("POSTGRES_USER", "signal-detection")
    pw = os.environ.get("POSTGRES_PASSWORD", "signal-detection")
    conn = psycopg2.connect(
        host=host, port=port,
        dbname="signal-detection-test", user=user, password=pw,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP SCHEMA public CASCADE")
    cur.execute("CREATE SCHEMA public")
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def db_setup() -> None:
    """Create test DB, wipe schema, init tables, and seed."""
    _create_test_db()
    _wipe_schema()
    init_db()
    seed()


@pytest.fixture(scope="session")
def user_key(db_setup: None) -> str:
    """Return a Bearer token that authenticates as a regular user."""
    token = "test-user-token"
    _CALLERS[token] = {"id": 1, "role": "user"}
    return token


@pytest.fixture
async def client(db_setup: None) -> AsyncClient:
    """Return an async HTTP test client with auth mocked out."""
    app = create_app()
    app.dependency_overrides[require_auth] = _auth_override
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture
async def real_auth_client(db_setup: None) -> AsyncClient:
    """Return a test client that exercises real auth logic."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_jobs() -> None:
    """Truncate job and classification rows after each test."""
    yield
    with get_db() as conn:
        conn.execute(
            "TRUNCATE classifications, classification_jobs"
            " RESTART IDENTITY CASCADE"
        )
