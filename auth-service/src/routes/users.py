"""Routes for /users — admin user management."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_admin
from db import transaction
from models.domains import (
    get_domain_slugs_for_user,
    get_domains_by_slugs,
    replace_user_domains,
)
from models.users import get_user_by_id, list_users, update_user_fields

router = APIRouter()


def _serialize(user: dict, domains: list[str]) -> dict:
    """Build the public user response dict."""
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "is_active": user["is_active"],
        "created_at": user["created_at"].isoformat(),
        "last_login_at": (
            user["last_login_at"].isoformat()
            if user["last_login_at"]
            else None
        ),
        "domains": domains,
    }


@router.get("/users")
async def get_users(
    caller: dict = Depends(require_admin),
) -> list[dict]:
    """List all users — admin only."""
    users = list_users()
    return [
        _serialize(u, get_domain_slugs_for_user(u["id"]))
        for u in users
    ]


@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    caller: dict = Depends(require_admin),
) -> dict:
    """Return a single user record — admin only."""
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return _serialize(user, get_domain_slugs_for_user(user_id))


class PatchUserIn(BaseModel):
    """Request body for PATCH /users/{id}."""

    is_active: Optional[bool] = None
    role: Optional[Literal["admin", "user"]] = None
    domain_slugs: Optional[list[str]] = None


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int,
    body: PatchUserIn,
    caller: dict = Depends(require_admin),
) -> dict:
    """Update is_active, role, and/or domain associations — admin only."""
    with transaction():
        user = get_user_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=404, detail="User not found."
            )

        if body.domain_slugs is not None:
            domain_rows = get_domains_by_slugs(body.domain_slugs)
            found = {r["slug"] for r in domain_rows}
            unknown = [
                s for s in body.domain_slugs if s not in found
            ]
            if unknown:
                raise HTTPException(
                    status_code=404,
                    detail=f"Unknown domain slugs: {unknown}",
                )
            replace_user_domains(
                user_id, [r["id"] for r in domain_rows]
            )

        updated = update_user_fields(
            user_id, body.is_active, body.role
        )
        user = updated if updated is not None else user
        domains = get_domain_slugs_for_user(user_id)
    return _serialize(user, domains)
