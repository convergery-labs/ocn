"""User management routes - create, list, rotate key, deactivate."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

import models.user as user_model
from auth import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserRequest(BaseModel):
    name: str
    email: str


class RotateKeyRequest(BaseModel):
    user_id: str


class SetPasswordRequest(BaseModel):
    password: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    is_active: bool
    has_api_key: bool
    has_google: bool
    created_at: Any
    last_seen_at: Any = None


class CreateUserResponse(BaseModel):
    user: dict
    api_key: str
    note: str


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)) -> dict:
    """Return the currently authenticated user."""
    return current_user


@router.get("/", response_model=list[UserResponse])
def list_users(_: dict = Depends(get_current_user)) -> list[dict[str, Any]]:
    """List all users."""
    return user_model.get_all()


@router.post("/", response_model=CreateUserResponse, status_code=201)
def create_user(
    body: CreateUserRequest,
    _: dict = Depends(get_current_user),
) -> dict:
    """Create a new user and return their API key (shown once - store it safely)."""
    try:
        user, raw_key = user_model.create(body.name, body.email)
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Email already exists")
        raise
    return {
        "user": user,
        "api_key": raw_key,
        "note": "Store this key securely - it cannot be retrieved again. Use POST /users/rotate to generate a new one.",
    }


@router.post("/rotate", response_model=dict)
def rotate_key(
    body: RotateKeyRequest,
    _: dict = Depends(get_current_user),
) -> dict:
    """Rotate the API key for a user (invalidates the old one immediately)."""
    new_key = user_model.rotate_key(body.user_id)
    return {
        "user_id": body.user_id,
        "api_key": new_key,
        "note": "Old key is now invalid. Store this new key securely.",
    }


@router.post("/{user_id}/set-password", status_code=204)
def set_password(
    user_id: str,
    body: SetPasswordRequest,
    _: dict = Depends(get_current_user),
) -> None:
    """Set or update the password for a user."""
    user_model.set_password(user_id, body.password)


@router.delete("/{user_id}", status_code=204)
def deactivate_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    """Deactivate a user (revokes all their API keys)."""
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    user_model.deactivate(user_id)
