"""User data models and database access functions."""
from datetime import datetime
from typing import Optional, TypedDict

from db import DuplicateError, get_db  # noqa: F401

__all__ = [
    "UserRow",
    "create_user",
    "get_user_by_username",
    "update_last_login",
]


class UserRow(TypedDict):
    """A row from the users table."""

    id: int
    username: str
    email: str
    password_hash: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]


def create_user(
    username: str,
    email: str,
    password_hash: str,
    role: str = "user",
) -> UserRow:
    """Insert a new user and return its row.

    Args:
        username: Unique display name.
        email: Unique email address.
        password_hash: bcrypt digest; plaintext must never be passed here.
        role: ``'admin'`` or ``'user'``.

    Returns:
        The newly created row.

    Raises:
        DuplicateError: if username or email already exists.
    """
    with get_db() as conn:
        row = conn.execute(
            "INSERT INTO users (username, email, password_hash, role)"
            " VALUES (?, ?, ?, ?) RETURNING *",
            (username, email, password_hash, role),
        ).fetchone()
    return dict(row)  # type: ignore[return-value]


def get_user_by_username(username: str) -> Optional[UserRow]:
    """Return the user row for *username*, or ``None`` if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    return dict(row) if row else None  # type: ignore[return-value]


def update_last_login(user_id: int) -> None:
    """Set last_login_at to now for *user_id*."""
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET last_login_at = CURRENT_TIMESTAMP"
            " WHERE id = ?",
            (user_id,),
        )
