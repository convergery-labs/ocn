"""Routes for /register and /login."""
import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import DuplicateError
from jwt_utils import issue_token
from models.domains import (
    attach_domains_to_user,
    get_domain_slugs_for_user,
    get_domains_by_slugs,
)
from models.users import create_user, get_user_by_username, update_last_login

router = APIRouter()


class RegisterIn(BaseModel):
    """Request body for POST /register."""

    username: str
    email: str
    password: str
    domain_slugs: list[str]


class LoginIn(BaseModel):
    """Request body for POST /login."""

    username: str
    password: str


@router.post("/register", status_code=201)
async def register(body: RegisterIn) -> dict:
    """Create a new user account with domain associations."""
    domain_rows = get_domains_by_slugs(body.domain_slugs)
    found_slugs = {r["slug"] for r in domain_rows}
    unknown = [s for s in body.domain_slugs if s not in found_slugs]
    if unknown:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown domain slugs: {unknown}",
        )

    password_hash = bcrypt.hashpw(
        body.password.encode(), bcrypt.gensalt()
    ).decode()

    try:
        user = create_user(
            username=body.username,
            email=body.email,
            password_hash=password_hash,
        )
    except DuplicateError:
        raise HTTPException(
            status_code=409, detail="Username or email already taken."
        )

    attach_domains_to_user(user["id"], [r["id"] for r in domain_rows])

    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "domains": [r["slug"] for r in domain_rows],
    }


@router.post("/login")
async def login(body: LoginIn) -> dict:
    """Verify credentials and return a signed JWT."""
    user = get_user_by_username(body.username)
    if user is None or not bcrypt.checkpw(
        body.password.encode(), user["password_hash"].encode()
    ):
        raise HTTPException(
            status_code=401, detail="Invalid credentials."
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=403, detail="Account is inactive."
        )

    update_last_login(user["id"])
    domains = get_domain_slugs_for_user(user["id"])

    token = issue_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        domains=domains,
    )
    return {"access_token": token, "token_type": "bearer"}
