"""Authentication dependency for research-universe.

Current:  API key bearer tokens (ru_<random>)
Future:   Google OAuth - add a second branch in get_current_user()
          that validates a Google ID token and looks up by google_id.
          No schema changes required.
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import models.user as user_model

# auto_error=False so we can return a friendlier 401 message
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Validate the bearer token and return the authenticated user.

    Called as a FastAPI dependency on every protected route.

    To add Google OAuth later:
        1. Check if credentials.credentials looks like a Google JWT
           (it will NOT start with 'ru_')
        2. Verify it with google-auth library
        3. Look up the user by google_id
        4. Return the same dict shape: {id, name, email}
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header. Include: Authorization: Bearer ru_<your_key>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # ── Session token branch (password login) ────────────────────────────
    if token.startswith("ru_sess_"):
        user = user_model.get_by_session_token(token)
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired - please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── API key branch (CLI / direct) ─────────────────────────────────────
    if token.startswith("ru_"):
        user = user_model.get_by_api_key(token)
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ── Google OAuth branch (future - placeholder) ────────────────────────
    # if _looks_like_google_jwt(token):
    #     user = _verify_google_token(token)
    #     return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unrecognised token format",
        headers={"WWW-Authenticate": "Bearer"},
    )
