"""User data models and database access functions."""
from datetime import datetime
from typing import Optional, TypedDict

from db import DuplicateError, get_db  # noqa: F401

__all__ = [
    "UserRow",
    "create_user",
    "get_user_by_id",
    "get_user_by_username",
    "get_user_by_email",
    "list_users",
    "update_last_login",
    "update_user_fields",
    "delete_user",
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


def get_user_by_email(email: str) -> Optional[UserRow]:
    """Return the user row for *email*, or ``None`` if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,),
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


def list_users() -> list[UserRow]:
    """Return all user rows ordered by id."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]  # type: ignore[return-value]


def get_user_by_id(user_id: int) -> Optional[UserRow]:
    """Return the user row for *user_id*, or ``None`` if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None  # type: ignore[return-value]


def update_user_fields(
    user_id: int,
    is_active: Optional[bool],
    role: Optional[str],
    username: Optional[str] = None,
) -> Optional[UserRow]:
    """Update ``is_active``, ``role``, and/or ``username`` for *user_id*.

    Returns the updated row, or ``None`` if the user does not exist.
    If no fields are provided, returns the current row unchanged.
    """
    updates: list[str] = []
    params: list = []
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(is_active)
    if role is not None:
        updates.append("role = ?")
        params.append(role)
    if username is not None:
        updates.append("username = ?")
        params.append(username)
    if not updates:
        return get_user_by_id(user_id)
    params.append(user_id)
    with get_db() as conn:
        row = conn.execute(
            f"UPDATE users SET {', '.join(updates)}"
            " WHERE id = ? RETURNING *",
            tuple(params),
        ).fetchone()
    return dict(row) if row else None  # type: ignore[return-value]


def delete_user(user_id: int) -> bool:
    """Delete user by *user_id*. Returns True if a row was deleted."""
    with get_db() as conn:
        result = conn.execute(
            "DELETE FROM users WHERE id = ? RETURNING id", (user_id,)
        ).fetchone()
    return result is not None
