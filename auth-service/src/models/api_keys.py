"""API key data models and database access functions."""
import hashlib
import secrets
from datetime import datetime
from typing import Optional, TypedDict

from db import get_db

KEY_PREFIX = "csec_"


class ApiKeyRow(TypedDict):
    """A row from the api_keys table."""

    id: int
    key_hash: str
    label: Optional[str]
    role: str
    created_by: Optional[int]
    created_at: datetime
    last_used_at: Optional[datetime]


def generate_key() -> str:
    """Generate a new plaintext API key.

    Returns:
        A key of the form ``csec_<64 hex chars>``.
    """
    return KEY_PREFIX + secrets.token_hex(32)


def hash_key(key: str) -> str:
    """Return the SHA-256 hex digest of *key*."""
    return hashlib.sha256(key.encode()).hexdigest()


def create_api_key(
    key: str,
    label: Optional[str],
    role: str,
    created_by: Optional[int],
) -> ApiKeyRow:
    """Insert a new API key and return its row.

    Args:
        key: Plaintext key; only its hash is stored.
        label: Human-readable identifier.
        role: ``'admin'`` or ``'user'``.
        created_by: Id of the key that created this one; ``None`` for
            the seed key.

    Returns:
        The newly created row (without the plaintext key).
    """
    key_hash = hash_key(key)
    with get_db() as conn:
        row = conn.execute(
            "INSERT INTO api_keys (key_hash, label, role, created_by)"
            " VALUES (?, ?, ?, ?) RETURNING *",
            (key_hash, label, role, created_by),
        ).fetchone()
    return dict(row)  # type: ignore[return-value]


def get_by_hash(key_hash: str) -> Optional[ApiKeyRow]:
    """Return the api_key row for *key_hash*, or ``None`` if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
    return dict(row) if row else None  # type: ignore[return-value]


def touch_last_used(key_id: int) -> None:
    """Update last_used_at to now for *key_id*."""
    with get_db() as conn:
        conn.execute(
            "UPDATE api_keys SET last_used_at = CURRENT_TIMESTAMP"
            " WHERE id = ?",
            (key_id,),
        )


def list_api_keys() -> list[ApiKeyRow]:
    """Return all api_key rows ordered by id (key_hash excluded)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, label, role, created_by, created_at,"
            " last_used_at FROM api_keys ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]  # type: ignore[return-value]


def has_any_admin_key() -> bool:
    """Return True if at least one admin key exists."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM api_keys WHERE role = 'admin' LIMIT 1"
        ).fetchone()
    return row is not None
