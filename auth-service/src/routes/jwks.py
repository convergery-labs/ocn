"""Route for GET /jwks — returns the RS256 public key in JWKS format."""
import base64
import os
from typing import Optional

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import APIRouter

router = APIRouter()

_JWKS: Optional[dict] = None


def _int_to_base64url(n: int) -> str:
    """Encode an integer as a Base64URL string with no padding."""
    length = (n.bit_length() + 7) // 8
    return (
        base64.urlsafe_b64encode(n.to_bytes(length, "big"))
        .rstrip(b"=")
        .decode()
    )


def _build_jwks() -> dict:
    """Derive JWKS from the AUTH_JWT_PRIVATE_KEY env var."""
    pem = os.environ["AUTH_JWT_PRIVATE_KEY"].encode()
    private_key = load_pem_private_key(pem, password=None)
    pub_numbers = private_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "n": _int_to_base64url(pub_numbers.n),
                "e": _int_to_base64url(pub_numbers.e),
            }
        ]
    }


@router.get("/jwks")
async def get_jwks() -> dict:
    """Return the RS256 public key in JWKS format (no auth required)."""
    global _JWKS
    if _JWKS is None:
        _JWKS = _build_jwks()
    return _JWKS
