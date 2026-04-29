"""Shared keyset pagination cursor utilities for OCN services."""
import base64
import json


def encode_cursor(payload: dict) -> str:
    """Encode a pagination payload as an opaque base64 cursor string."""
    return base64.b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    """Decode a cursor string back to its payload dict.

    Raises:
        ValueError: if the cursor is malformed or not valid base64 JSON.
    """
    try:
        return json.loads(base64.b64decode(cursor).decode())
    except Exception as exc:
        raise ValueError("Invalid cursor") from exc
