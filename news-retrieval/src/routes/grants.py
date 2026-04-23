"""Routes for domain access grants.

API key lifecycle (create, list, delete) is managed by auth-service.
These endpoints manage which domains each key is permitted to access.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_admin
from models.api_key_domains import (
    grant_domains,
    list_granted_domains,
    revoke_domain,
)

router = APIRouter()


class DomainGrantIn(BaseModel):
    """Request body for POST /grants/{key_id}/domains."""

    domain_ids: list[int]


@router.post("/grants/{key_id}/domains", status_code=200)
async def post_api_key_domains(
    key_id: int,
    body: DomainGrantIn,
    caller: dict[str, Any] = Depends(require_admin),
) -> list[dict]:
    """Grant domain access to an API key — admin only.

    Upserts grants for the given domain_ids and returns the updated
    full domain list for the key.
    """
    return grant_domains(key_id, body.domain_ids)


@router.delete(
    "/grants/{key_id}/domains/{domain_id}",
    status_code=204,
)
async def delete_api_key_domain(
    key_id: int,
    domain_id: int,
    caller: dict[str, Any] = Depends(require_admin),
) -> None:
    """Revoke a single domain grant from an API key — admin only."""
    deleted = revoke_domain(key_id, domain_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No grant for key {key_id}"
                f" on domain {domain_id}."
            ),
        )
