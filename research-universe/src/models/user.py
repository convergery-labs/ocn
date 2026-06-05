"""DB query functions for universe_users."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

SESSION_TTL = timedelta(hours=8)
from typing import Any

import bcrypt

from db import DuplicateError, get_db

# API key prefix - makes keys identifiable in logs and config
_PREFIX = "ru_"


def generate_api_key() -> tuple[str, str]:
    """Return (raw_key, hashed_key). Store the hash; give raw to the user.

    We use token_urlsafe(24) → 32-char base64 string → total key ≤ 35 bytes,
    safely within bcrypt's 72-byte limit.
    """
    raw = _PREFIX + secrets.token_urlsafe(24)
    hashed = bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()
    return raw, hashed


def verify_api_key(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except Exception:
        return False


def create(name: str, email: str) -> tuple[dict[str, Any], str]:
    """Create a new user and return (user_record, raw_api_key)."""
    raw, hashed = generate_api_key()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO universe_users (name, email, api_key_hash)
            VALUES (:name, :email, :hash)
            RETURNING id::text, name, email, is_active, created_at
            """,
            {"name": name, "email": email, "hash": hashed},
        )
        user = dict(cur.fetchone())
    return user, raw


def get_all() -> list[dict[str, Any]]:
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT id::text, name, email, is_active, created_at, last_seen_at,
                   (api_key_hash IS NOT NULL) AS has_api_key,
                   (google_id IS NOT NULL)    AS has_google
            FROM universe_users
            ORDER BY created_at
            """
        )
        return [dict(r) for r in cur.fetchall()]


def get_by_api_key(raw: str) -> dict[str, Any] | None:
    """Look up a user by raw API key. Returns user dict or None."""
    if not raw.startswith(_PREFIX):
        return None
    with get_db() as conn:
        # Fetch all active users that have an api_key_hash set
        cur = conn.execute(
            """
            SELECT id::text, name, email, api_key_hash, is_active
            FROM universe_users
            WHERE is_active = TRUE AND api_key_hash IS NOT NULL
            """
        )
        for row in cur.fetchall():
            if verify_api_key(raw, row["api_key_hash"]):
                touch_last_seen(row["id"])
                return {"id": row["id"], "name": row["name"], "email": row["email"]}
    return None


def touch_last_seen(user_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE universe_users SET last_seen_at = :now WHERE id = :id",
            {"id": user_id, "now": datetime.now(timezone.utc)},
        )


def rotate_key(user_id: str) -> str:
    """Generate a new API key for a user (old key revoked immediately)."""
    raw, hashed = generate_api_key()
    with get_db() as conn:
        conn.execute(
            "UPDATE universe_users SET api_key_hash = :hash WHERE id = :id",
            {"id": user_id, "hash": hashed},
        )
    return raw


def deactivate(user_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE universe_users SET is_active = FALSE WHERE id = :id",
            {"id": user_id},
        )


def get_by_email(email: str) -> dict[str, Any] | None:
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT id::text, name, email, password_hash, is_active
            FROM universe_users
            WHERE email = :email AND is_active = TRUE
            """,
            {"email": email},
        )
        row = cur.fetchone()
        return dict(row) if row else None


def set_password(user_id: str, password: str) -> None:
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with get_db() as conn:
        conn.execute(
            "UPDATE universe_users SET password_hash = :hash WHERE id = :id",
            {"id": user_id, "hash": hashed},
        )


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except Exception:
        return False


def _hash_session_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_session(user_id: str) -> str:
    """Generate a session token, store its SHA-256 hash, return the raw token."""
    token = "ru_sess_" + secrets.token_urlsafe(32)
    token_hash = _hash_session_token(token)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    with get_db() as conn:
        conn.execute(
            "UPDATE universe_users SET session_token = :hash, session_expires_at = :exp WHERE id = :id",
            {"id": user_id, "hash": token_hash, "exp": expires_at},
        )
    return token


def get_by_session_token(token: str) -> dict[str, Any] | None:
    token_hash = _hash_session_token(token)
    now = datetime.now(timezone.utc)
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT id::text, name, email, session_expires_at
            FROM universe_users
            WHERE session_token = :hash AND is_active = TRUE
            """,
            {"hash": token_hash},
        )
        row = cur.fetchone()
        if not row:
            return None
        if row["session_expires_at"] and row["session_expires_at"] < now:
            # Expired - clear it
            conn.execute(
                "UPDATE universe_users SET session_token = NULL, session_expires_at = NULL WHERE id = :id",
                {"id": row["id"]},
            )
            return None
        # Slide the expiry window
        new_exp = now + SESSION_TTL
        conn.execute(
            "UPDATE universe_users SET last_seen_at = :now, session_expires_at = :exp WHERE id = :id",
            {"id": row["id"], "now": now, "exp": new_exp},
        )
        return {"id": row["id"], "name": row["name"], "email": row["email"]}


def clear_session(user_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE universe_users SET session_token = NULL WHERE id = :id",
            {"id": user_id},
        )
