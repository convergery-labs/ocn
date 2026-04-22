"""FastAPI dependency functions for authentication and authorisation."""
import os
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException

from models.api_keys import ApiKeyRow, get_by_hash, hash_key, touch_last_used


async def require_auth(
    authorization: str = Header(...),
) -> dict[str, Any]:
    """Validate the Bearer token and return key metadata.

    When ``AUTH_SERVICE_URL`` is set, delegates to
    ``POST {AUTH_SERVICE_URL}/validate``. Falls back to local auth if
    the remote service is unreachable. When ``AUTH_SERVICE_URL`` is not
    set, validates locally against the news-retrieval DB.

    Raises:
        HTTPException 401: if the header is absent or the key is unknown.
    """
    auth_service_url = os.environ.get("AUTH_SERVICE_URL")

    if auth_service_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{auth_service_url}/validate",
                    headers={"Authorization": authorization},
                )
            if resp.status_code == 200:
                data = resp.json()
                return {"id": data["key_id"], "role": data["role"]}
            raise HTTPException(
                status_code=401, detail="Invalid or unknown API key."
            )
        except httpx.HTTPError:
            pass  # auth-service unreachable — fall through to local auth

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Invalid Authorization header."
        )
    raw_key = authorization[len("Bearer "):]
    key_hash = hash_key(raw_key)
    row = get_by_hash(key_hash)
    if row is None:
        raise HTTPException(
            status_code=401, detail="Invalid or unknown API key."
        )
    touch_last_used(row["id"])
    return row


def require_admin(
    caller: ApiKeyRow = Depends(require_auth),
) -> ApiKeyRow:
    """Require the caller to hold the admin role.

    Raises:
        HTTPException 403: if the caller is not an admin.
    """
    if caller["role"] != "admin":
        raise HTTPException(
            status_code=403, detail="Admin access required."
        )
    return caller
