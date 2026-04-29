"""Tests for POST /register and POST /login."""
import os

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey,
)
from httpx import AsyncClient

from conftest import _test_private_key


def _public_key() -> object:
    """Return the RSA public key corresponding to the test private key."""
    return _test_private_key.public_key()


# ---------------------------------------------------------------------------
# /register
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_success(
    client: AsyncClient,
    seed_domains: list[str],
) -> None:
    """Happy path: creates user and returns expected shape."""
    resp = await client.post("/register", json={
        "username": "alice",
        "email": "alice@example.com",
        "password": "s3cr3t",
        "domain_slugs": ["ai_news"],
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert body["role"] == "user"
    assert body["domains"] == ["ai_news"]
    assert "id" in body
    assert "password" not in body
    assert "password_hash" not in body


@pytest.mark.asyncio
async def test_register_duplicate_username(
    client: AsyncClient,
    seed_domains: list[str],
) -> None:
    """Duplicate username returns 409."""
    payload = {
        "username": "bob",
        "email": "bob@example.com",
        "password": "pass",
        "domain_slugs": [],
    }
    await client.post("/register", json=payload)
    payload["email"] = "bob2@example.com"
    resp = await client.post("/register", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_unknown_domain(
    client: AsyncClient,
    seed_domains: list[str],
) -> None:
    """Unknown domain slug returns 404."""
    resp = await client.post("/register", json={
        "username": "carol",
        "email": "carol@example.com",
        "password": "pass",
        "domain_slugs": ["nonexistent"],
    })
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_success(
    client: AsyncClient,
    seed_domains: list[str],
) -> None:
    """Correct credentials return a valid RS256 JWT."""
    await client.post("/register", json={
        "username": "dave",
        "email": "dave@example.com",
        "password": "hunter2",
        "domain_slugs": ["ai_news", "robotics"],
    })
    resp = await client.post("/login", json={
        "username": "dave",
        "password": "hunter2",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    token = body["access_token"]
    payload = jwt.decode(
        token,
        _public_key(),
        algorithms=["RS256"],
    )
    assert payload["username"] == "dave"
    assert payload["role"] == "user"
    assert set(payload["domains"]) == {"ai_news", "robotics"}
    assert "sub" in payload
    assert "exp" in payload


@pytest.mark.asyncio
async def test_login_wrong_password(
    client: AsyncClient,
    seed_domains: list[str],
) -> None:
    """Wrong password returns 401."""
    await client.post("/register", json={
        "username": "eve",
        "email": "eve@example.com",
        "password": "correct",
        "domain_slugs": [],
    })
    resp = await client.post("/login", json={
        "username": "eve",
        "password": "wrong",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(client: AsyncClient) -> None:
    """Unknown username returns 401 (same as wrong password)."""
    resp = await client.post("/login", json={
        "username": "nobody",
        "password": "whatever",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_account(
    client: AsyncClient,
    seed_domains: list[str],
) -> None:
    """Inactive account returns 403."""
    import os
    import psycopg2

    await client.post("/register", json={
        "username": "frank",
        "email": "frank@example.com",
        "password": "pass",
        "domain_slugs": [],
    })

    # Deactivate the user directly in the DB.
    conn = psycopg2.connect(
        host=os.environ.get("AUTH_POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("AUTH_POSTGRES_PORT", "5432")),
        dbname="auth-service-test",
        user=os.environ.get("AUTH_POSTGRES_USER", "auth-service"),
        password=os.environ.get("AUTH_POSTGRES_PASSWORD", "auth-service"),
    )
    conn.autocommit = True
    conn.cursor().execute(
        "UPDATE users SET is_active = FALSE WHERE username = 'frank'"
    )
    conn.close()

    resp = await client.post("/login", json={
        "username": "frank",
        "password": "pass",
    })
    assert resp.status_code == 403
