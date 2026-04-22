"""Routes for /validate."""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from models.api_keys import get_by_hash, hash_key, touch_last_used

router = APIRouter()


@router.post("/validate")
async def post_validate(
    authorization: Optional[str] = Header(None),
) -> dict:
    """Validate a Bearer token and return key metadata.

    Returns:
        ``{"valid": true, "role": ..., "key_id": ...}`` on success.

    Raises:
        HTTPException 401: for a missing, malformed, or unknown key.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Invalid Authorization header."
        )
    raw_key = authorization[len("Bearer "):]
    row = get_by_hash(hash_key(raw_key))
    if row is None:
        raise HTTPException(
            status_code=401, detail="Invalid or unknown API key."
        )
    touch_last_used(row["id"])
    return {"valid": True, "role": row["role"], "key_id": row["id"]}
