"""Tests for GET /jwks."""
import base64

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPublicKey,
)
from httpx import AsyncClient

from jwt_utils import issue_token


def _base64url_to_int(value: str) -> int:
    """Decode a Base64URL string (no padding) to an integer."""
    padding = "=" * (-len(value) % 4)
    return int.from_bytes(
        base64.urlsafe_b64decode(value + padding), "big"
    )


def _public_key_from_jwks(key: dict) -> RSAPublicKey:
    """Reconstruct an RSA public key from a JWKS key entry."""
    n = _base64url_to_int(key["n"])
    e = _base64url_to_int(key["e"])
    return RSAPublicNumbers(e, n).public_key()


@pytest.mark.asyncio
async def test_get_jwks_returns_200(client: AsyncClient) -> None:
    """GET /jwks should return HTTP 200 with no auth."""
    response = await client.get("/jwks")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_jwks_shape(client: AsyncClient) -> None:
    """GET /jwks should return a valid JWKS structure."""
    response = await client.get("/jwks")
    body = response.json()
    assert "keys" in body
    assert len(body["keys"]) == 1
    key = body["keys"][0]
    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert "n" in key
    assert "e" in key


@pytest.mark.asyncio
async def test_jwks_public_key_verifies_issued_jwt(
    client: AsyncClient,
) -> None:
    """Public key from JWKS must verify a JWT issued by issue_token."""
    response = await client.get("/jwks")
    key_entry = response.json()["keys"][0]
    public_key = _public_key_from_jwks(key_entry)

    token = issue_token(
        user_id=1,
        username="testuser",
        role="user",
        domains=["ai_news"],
    )
    payload = jwt.decode(token, public_key, algorithms=["RS256"])
    assert payload["sub"] == "1"
    assert payload["username"] == "testuser"
    assert payload["role"] == "user"
