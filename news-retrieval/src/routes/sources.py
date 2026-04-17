"""Routes for /sources."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_auth
from db import DuplicateError
from models.api_keys import ApiKeyRow
from models.domains import get_domain_by_id
from models.sources import SourceIn, create_source, list_sources

router = APIRouter()


@router.get("/sources")
async def get_sources(
    domain: Optional[str] = Query(default=None),
) -> list[dict]:
    """Return all sources, optionally filtered by domain slug."""
    return list_sources(domain)


@router.post("/sources", status_code=201)
async def post_source(
    body: SourceIn,
    caller: ApiKeyRow = Depends(require_auth),
) -> dict:
    """Add a new RSS feed source.

    Users may only add sources to domains they own.
    Admins may add to any domain.
    """
    if caller["role"] != "admin":
        try:
            domain = get_domain_by_id(body.domain_id)
        except (TypeError, KeyError):
            raise HTTPException(
                status_code=404,
                detail=f"domain_id {body.domain_id} not found.",
            )
        if domain.get("created_by") != caller["id"]:
            raise HTTPException(
                status_code=403,
                detail="You do not own this domain.",
            )
    try:
        return create_source(body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DuplicateError:
        raise HTTPException(
            status_code=409,
            detail=f"URL '{body.url}' already exists.",
        )
