"""Shared pytest fixtures for the news-retrieval test suite."""
import base64
import json
import os
import sys
from unittest.mock import patch

import psycopg2
import psycopg2.errors
import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "src"),
)
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "..", "shared", "src"
    ),
)

# Must be set before any src imports so DB connections hit the test DB.
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ["POSTGRES_DB"] = "news-retrieval-test"
os.environ.setdefault("POSTGRES_USER", "news-retrieval")
os.environ.setdefault("POSTGRES_PASSWORD", "news-retrieval")
os.environ["OPENROUTER_MODEL"] = "test-model"

from app import create_app  # noqa: E402
from db import get_db, init_db  # noqa: E402
from models.api_key_domains import grant_domains  # noqa: E402
from models.domains import insert_domain  # noqa: E402
from seed import seed  # noqa: E402


def _ocn_caller(sub: int, role: str) -> str:
    """Build a valid x-ocn-caller header value."""
    payload = json.dumps({"sub": sub, "role": role, "domains": []})
    return base64.b64encode(payload.encode()).decode()

_FAKE_ARTICLES = [
    {
        "url": f"http://example.com/article-{i}",
        "title": f"Test Article {i}",
        "summary": "A test summary.",
        "source": "Test Feed",
        "published": "2026-01-01T00:00:00",
    }
    for i in range(3)
]


def _create_test_db() -> None:
    """Create the news-retrieval-test database if absent."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    user = os.environ.get("POSTGRES_USER", "news-retrieval")
    pw = os.environ.get("POSTGRES_PASSWORD", "news-retrieval")
    conn = psycopg2.connect(
        host=host, port=port,
        dbname="postgres", user=user, password=pw,
    )
    conn.autocommit = True
    try:
        conn.cursor().execute(
            'CREATE DATABASE "news-retrieval-test"'
        )
    except psycopg2.errors.DuplicateDatabase:
        pass
    finally:
        conn.close()


def _wipe_schema() -> None:
    """Drop and recreate the public schema in the test DB."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    user = os.environ.get("POSTGRES_USER", "news-retrieval")
    pw = os.environ.get("POSTGRES_PASSWORD", "news-retrieval")
    conn = psycopg2.connect(
        host=host, port=port,
        dbname="news-retrieval-test", user=user, password=pw,
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
def admin_key(db_setup: None) -> str:
    """Return an x-ocn-caller header value for an admin caller."""
    return _ocn_caller(1, "admin")


@pytest.fixture(scope="session")
def user_key(db_setup: None) -> tuple[str, int]:
    """Return (x-ocn-caller header value, caller_id) for a regular-user."""
    caller_id = 2
    return _ocn_caller(caller_id, "user"), caller_id


@pytest.fixture(scope="session")
def other_user_key(db_setup: None) -> tuple[str, int]:
    """Return (x-ocn-caller header value, caller_id) for a second user."""
    caller_id = 3
    return _ocn_caller(caller_id, "user"), caller_id


@pytest.fixture(scope="session")
def user_domain(user_key: tuple[str, int]) -> int:
    """Return the id of a domain owned by and granted to user_key."""
    _, user_id = user_key
    domain_id = insert_domain(
        "Test Domain", "test-domain", None, user_id
    )
    grant_domains(user_id, [domain_id])
    return domain_id


@pytest.fixture(scope="session")
def daily_frequency_id(db_setup: None) -> int:
    """Return the id of the 'daily' frequency row."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM frequencies WHERE name = 'daily'"
        ).fetchone()
    return row["id"]


@pytest.fixture
async def client() -> AsyncClient:
    """Return an async HTTP test client with real auth logic."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def mock_trafilatura(monkeypatch) -> None:
    """Patch trafilatura to avoid live HTTP fetches in unit tests.

    Tests that exercise the Trafilatura fallback path override this
    with their own ``patch`` context managers.
    """
    import trafilatura as _traf
    monkeypatch.setattr(_traf, "fetch_url", lambda url: None)
    monkeypatch.setattr(_traf, "extract", lambda html: None)


@pytest.fixture(autouse=True)
def clean_runs() -> None:
    """Delete all run and article rows after each test."""
    yield
    with get_db() as db:
        db.execute("DELETE FROM articles")
        db.execute("DELETE FROM runs")


@pytest.fixture
def mock_pipeline():
    """Patch pipeline.run to return dummy articles instantly."""
    with patch(
        "pipeline.run",
        return_value={"articles": _FAKE_ARTICLES},
    ) as m:
        yield m
