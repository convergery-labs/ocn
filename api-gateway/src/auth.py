"""FastAPI dependency functions for authentication and authorisation."""
import base64
import os
from typing import Any, Optional

import httpx
import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer()
_auth_client = httpx.AsyncClient(timeout=5.0)
_cached_public_key: Optional[object] = None


def _base64url_to_int(val: str) -> int:
    """Decode a Base64URL-encoded JWKS integer field (n or e) to a Python int."""
    padded = val + "=" * (-len(val) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


async def _get_public_key() -> object:
    """Return the cached RS256 public key, fetching from JWKS on first call.

    Raises:
        HTTPException 503: if GATEWAY_AUTH_URL is unset or auth-service is
            unreachable.
    """
    global _cached_public_key
    if _cached_public_key is not None:
        return _cached_public_key

    auth_url = os.environ.get("GATEWAY_AUTH_URL")
    if not auth_url:
        raise HTTPException(
            status_code=503,
            detail="GATEWAY_AUTH_URL is not configured.",
        )
    try:
        resp = await _auth_client.get(f"{auth_url}/jwks")
        resp.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(
            status_code=503,
            detail="Auth service unreachable.",
        )

    key_data = resp.json()["keys"][0]
    numbers = RSAPublicNumbers(
        e=_base64url_to_int(key_data["e"]),
        n=_base64url_to_int(key_data["n"]),
    )
    _cached_public_key = numbers.public_key(default_backend())
    return _cached_public_key


async def _validate_jwt(token: str) -> dict[str, Any]:
    """Verify an RS256 JWT and return caller identity.

    Raises:
        HTTPException 401: if the token is expired or has an invalid signature.
        HTTPException 503: if the public key cannot be fetched.
    """
    public_key = await _get_public_key()
    try:
        payload = jwt.decode(token, public_key, algorithms=["RS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="JWT has expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid JWT.")
    return {
        "sub": payload["sub"],
        "role": payload["role"],
        "domains": payload.get("domains", []),
        "auth_type": "jwt",
    }


async def _validate_api_key(token: str) -> dict[str, Any]:
    """Validate an API key via auth-service POST /validate.

    Raises:
        HTTPException 401: if the key is rejected.
        HTTPException 503: if GATEWAY_AUTH_URL is unset or auth-service is
            unreachable.
    """
    auth_url = os.environ.get("GATEWAY_AUTH_URL")
    if not auth_url:
        raise HTTPException(
            status_code=503,
            detail="GATEWAY_AUTH_URL is not configured.",
        )
    try:
        resp = await _auth_client.post(
            f"{auth_url}/validate",
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=503,
            detail="Auth service unreachable.",
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail="Invalid or unknown API key.",
        )
    data = resp.json()
    return {
        "sub": data["key_id"],
        "role": data["role"],
        "domains": data.get("domains", []),
        "auth_type": "api_key",
    }


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict[str, Any]:
    """Validate the Bearer token — JWT or API key — and return caller identity.

    JWTs are identified by containing exactly two dots (three segments).
    All other tokens are treated as API keys and validated via the
    auth-service POST /validate endpoint.

    Raises:
        HTTPException 401: if the token is invalid or rejected.
        HTTPException 503: if a required upstream is unavailable.
    """
    token = credentials.credentials
    if token.count(".") == 2:
        return await _validate_jwt(token)
    return await _validate_api_key(token)


def require_admin(
    caller: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    """Require the caller to hold the admin role.

    Raises:
        HTTPException 403: if the caller is not an admin.
    """
    if caller["role"] != "admin":
        raise HTTPException(
            status_code=403, detail="Admin access required."
        )
    return caller
