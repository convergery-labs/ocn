"""Password-based login and logout endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

import models.user as user_model
from limiter import limiter
from auth import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest) -> dict:
    """Exchange email + password for a session token."""
    user = user_model.get_by_email(body.email)
    if not user or not user.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user_model.verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    token = user_model.create_session(user["id"])
    return {
        "session_token": token,
        "user": {"id": user["id"], "name": user["name"], "email": user["email"]},
    }


@router.post("/logout", status_code=204)
def logout(current_user: dict = Depends(get_current_user)) -> None:
    """Invalidate the current session token."""
    user_model.clear_session(current_user["id"])
