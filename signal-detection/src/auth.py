"""FastAPI dependency functions for authentication and authorisation."""
import base64
import json
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException


async def require_auth(
    x_ocn_caller: Optional[str] = Header(
        None, alias="x-ocn-caller"
    ),
) -> dict[str, Any]:
    """Extract caller identity from the x-ocn-caller header.

    The API gateway validates the Bearer token and injects this header
    as base64-encoded JSON before forwarding the request. The header
    payload is ``{"sub": int, "role": str, "domains": [int]}``.

    Returns a dict with ``id`` (int) and ``role`` (str).

    Raises:
        HTTPException 401: if the header is absent or cannot be decoded.
    """
    if not x_ocn_caller:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing x-ocn-caller header.",
        )
    try:
        payload = json.loads(base64.b64decode(x_ocn_caller))
        return {"id": payload["sub"], "role": payload["role"]}
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing x-ocn-caller header.",
        )


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
