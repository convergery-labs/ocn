"""FastAPI dependency functions for authentication and authorisation."""
import os
from typing import Any

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer()
_auth_client = httpx.AsyncClient(timeout=5.0)


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict[str, Any]:
    """Validate the Bearer token via the auth-service POST /validate.

    Delegates to ``POST {GATEWAY_AUTH_URL}/validate``.

    Raises:
        HTTPException 401: if the token is rejected by the auth-service.
        HTTPException 503: if GATEWAY_AUTH_URL is not configured or the
            auth-service is unreachable.
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
            headers={
                "Authorization": f"Bearer {credentials.credentials}"
            },
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
    }


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
