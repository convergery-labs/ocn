"""Routes for /api-keys."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_admin
from db import DuplicateError, get_db
from models.api_key_domains import (
    grant_domains,
    list_granted_domains,
    revoke_domain,
)
from models.api_keys import (
    ApiKeyRow,
    create_api_key,
    generate_key,
    get_api_key_by_id,
    list_api_keys,
)

router = APIRouter()


class ApiKeyIn(BaseModel):
    """Request body for POST /api-keys."""

    label: str
    role: Literal["admin", "user"]
    domain_ids: list[int] = []


class DomainGrantIn(BaseModel):
    """Request body for POST /api-keys/{key_id}/domains."""

    domain_ids: list[int]


def _assert_key_exists(key_id: int) -> ApiKeyRow:
    """Return the key row or raise 404."""
    row = get_api_key_by_id(key_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"API key {key_id} not found.",
        )
    return row


def _assert_domains_exist(domain_ids: list[int]) -> None:
    """Raise 400 if any domain_id does not exist."""
    if not domain_ids:
        return
    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM domains WHERE id = ANY(?)",
            (domain_ids,),
        ).fetchone()["n"]
    if count != len(domain_ids):
        raise HTTPException(
            status_code=400,
            detail="One or more domain_ids do not exist.",
        )


@router.get("/api-keys")
async def get_api_keys(
    caller: ApiKeyRow = Depends(require_admin),
) -> list[dict]:
    """Return all API keys (hashes excluded) — admin only."""
    return list_api_keys()


@router.post("/api-keys", status_code=201)
async def post_api_key(
    body: ApiKeyIn,
    caller: ApiKeyRow = Depends(require_admin),
) -> dict:
    """Create a new API key, optionally granting domains — admin only."""
    _assert_domains_exist(body.domain_ids)
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
            status_code=409,
            detail="Key hash collision — try again.",
        )
    if body.domain_ids:
        grant_domains(row["id"], body.domain_ids)
    return {**row, "key": key}


@router.post("/api-keys/{key_id}/domains", status_code=200)
async def post_api_key_domains(
    key_id: int,
    body: DomainGrantIn,
    caller: ApiKeyRow = Depends(require_admin),
) -> list[dict]:
    """Grant domain access to an API key — admin only.

    Upserts grants for the given domain_ids and returns the updated
    full domain list for the key.
    """
    _assert_key_exists(key_id)
    _assert_domains_exist(body.domain_ids)
    return grant_domains(key_id, body.domain_ids)


@router.delete("/api-keys/{key_id}/domains/{domain_id}",
               status_code=204)
async def delete_api_key_domain(
    key_id: int,
    domain_id: int,
    caller: ApiKeyRow = Depends(require_admin),
) -> None:
    """Revoke a single domain grant from an API key — admin only."""
    _assert_key_exists(key_id)
    deleted = revoke_domain(key_id, domain_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No grant for key {key_id} on domain {domain_id}."
            ),
        )
