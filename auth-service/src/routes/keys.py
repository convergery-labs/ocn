"""Routes for /keys."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_admin
from db import DuplicateError
from models.api_keys import (
    ApiKeyRow,
    create_api_key,
    generate_key,
    list_api_keys,
)

router = APIRouter()


class ApiKeyIn(BaseModel):
    """Request body for POST /keys."""

    label: str
    role: Literal["admin", "user"]


@router.get("/keys")
async def get_keys(
    caller: ApiKeyRow = Depends(require_admin),
) -> list[dict]:
    """Return all API keys (hashes excluded) — admin only."""
    return list_api_keys()


@router.post("/keys", status_code=201)
async def post_key(
    body: ApiKeyIn,
    caller: ApiKeyRow = Depends(require_admin),
) -> dict:
    """Create a new API key and return the plaintext key once — admin only."""
    try:
        key = generate_key()
        row = create_api_key(
            key,
            label=body.label,
            role=body.role,
            created_by=caller["id"],
        )
    except DuplicateError:
        raise HTTPException(
            status_code=409, detail="Key hash collision — try again."
        )
    return {**row, "key": key}
