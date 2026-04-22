"""FastAPI dependency functions for authentication and authorisation."""
from fastapi import Depends, Header, HTTPException

from models.api_keys import ApiKeyRow, get_by_hash, hash_key, touch_last_used


def require_auth(
    authorization: str = Header(...),
) -> ApiKeyRow:
    """Validate the Bearer token and return the matching api_key row.

    Raises:
        HTTPException 401: if the header is absent or the key is unknown.
    """
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
