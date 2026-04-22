"""Shared pytest fixtures for the auth-service test suite."""
import os
import sys

import psycopg2
import psycopg2.errors
import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "src"),
)

os.environ.setdefault("AUTH_POSTGRES_HOST", "localhost")
os.environ.setdefault("AUTH_POSTGRES_PORT", "5432")
os.environ["AUTH_POSTGRES_DB"] = "auth-service-test"
os.environ.setdefault("AUTH_POSTGRES_USER", "auth-service")
os.environ.setdefault("AUTH_POSTGRES_PASSWORD", "auth-service")

from app import create_app  # noqa: E402
from db import init_db  # noqa: E402
from models.api_keys import create_api_key, generate_key  # noqa: E402


def _create_test_db() -> None:
    """Create the auth-service-test database if absent."""
    host = os.environ.get("AUTH_POSTGRES_HOST", "localhost")
    port = int(os.environ.get("AUTH_POSTGRES_PORT", "5432"))
    user = os.environ.get("AUTH_POSTGRES_USER", "auth-service")
    pw = os.environ.get("AUTH_POSTGRES_PASSWORD", "auth-service")
    conn = psycopg2.connect(
        host=host, port=port,
        dbname="postgres", user=user, password=pw,
    )
    conn.autocommit = True
    try:
        conn.cursor().execute('CREATE DATABASE "auth-service-test"')
    except psycopg2.errors.DuplicateDatabase:
        pass
    finally:
        conn.close()


def _wipe_schema() -> None:
    """Drop and recreate the public schema in the test DB."""
    host = os.environ.get("AUTH_POSTGRES_HOST", "localhost")
    port = int(os.environ.get("AUTH_POSTGRES_PORT", "5432"))
    user = os.environ.get("AUTH_POSTGRES_USER", "auth-service")
    pw = os.environ.get("AUTH_POSTGRES_PASSWORD", "auth-service")
    conn = psycopg2.connect(
        host=host, port=port,
        dbname="auth-service-test", user=user, password=pw,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP SCHEMA public CASCADE")
    cur.execute("CREATE SCHEMA public")
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def db_setup() -> None:
    """Create test DB, wipe schema, and initialise tables."""
    _create_test_db()
    _wipe_schema()
    init_db()


@pytest.fixture(scope="session")
def admin_key(db_setup: None) -> str:
    """Return a plaintext admin API key for the test session."""
    key = generate_key()
    create_api_key(key, "test-admin", "admin", None)
    return key


@pytest.fixture(scope="session")
def user_key(db_setup: None) -> tuple[str, int]:
    """Return (plaintext_key, key_id) for a regular-user key."""
    key = generate_key()
    row = create_api_key(key, "test-user", "user", None)
    return key, row["id"]


@pytest.fixture
async def client() -> AsyncClient:
    """Return an async HTTP test client backed by the ASGI app."""
    application = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as c:
        yield c
