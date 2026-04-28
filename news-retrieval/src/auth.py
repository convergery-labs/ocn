"""FastAPI dependency functions for authentication and authorisation."""
import os
from typing import Any

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer()


class CallerInfo(dict):
    """Caller identity returned by require_auth.

    Always contains ``id`` (int) and ``role`` (str), sourced from the
    auth-service response.
    """


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict[str, Any]:
    """Validate the Bearer token via the auth-service.

    Delegates to ``POST {AUTH_SERVICE_URL}/validate``.

    Raises:
        HTTPException 401: if the token is rejected by auth-service.
        HTTPException 503: if AUTH_SERVICE_URL is not configured.
    """
    auth_service_url = os.environ.get("AUTH_SERVICE_URL")
    if not auth_service_url:
        raise HTTPException(
            status_code=503,
            detail="AUTH_SERVICE_URL is not configured.",
        )
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{auth_service_url}/validate",
                headers={
                    "Authorization": (
                        f"Bearer {credentials.credentials}"
                    )
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
    return {"id": data["key_id"], "role": data["role"]}


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
