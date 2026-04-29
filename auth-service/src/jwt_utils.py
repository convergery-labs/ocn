"""RS256 JWT issuance for auth-service."""
import os
from datetime import datetime, timezone, timedelta

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

__all__ = ["issue_token"]

_DEFAULT_EXPIRY = 3600


def _private_key() -> object:
    """Load the RS256 private key from AUTH_JWT_PRIVATE_KEY env var."""
    pem = os.environ["AUTH_JWT_PRIVATE_KEY"].encode()
    return load_pem_private_key(pem, password=None)


def issue_token(
    user_id: int,
    username: str,
    role: str,
    domains: list[str],
) -> str:
    """Sign and return a JWT for the given user.

    Args:
        user_id: The ``sub`` claim value.
        username: Included in payload for convenience.
        role: User role (``'admin'`` or ``'user'``).
        domains: Domain slugs the user is associated with.

    Returns:
        A signed RS256 JWT string.
    """
    expiry = int(
        os.environ.get("AUTH_JWT_EXPIRY_SECONDS", str(_DEFAULT_EXPIRY))
    )
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "domains": domains,
        "iat": now,
        "exp": now + timedelta(seconds=expiry),
    }
    return jwt.encode(payload, _private_key(), algorithm="RS256")
