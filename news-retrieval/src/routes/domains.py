"""Routes for /domains."""
from fastapi import APIRouter, Depends, HTTPException

from auth import require_auth
from controllers.domains import DomainIn, DomainPatch, create, get_all, update
from db import DuplicateError
from models.api_keys import ApiKeyRow

router = APIRouter()


@router.get("/domains")
async def get_domains() -> list[dict]:
    """Return all domains."""
    return get_all()


@router.post("/domains", status_code=201)
async def post_domain(
    body: DomainIn,
    caller: ApiKeyRow = Depends(require_auth),
) -> dict:
    """Create a domain owned by the caller."""
    try:
        return create(body, caller)
    except DuplicateError:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A domain with name '{body.name}' or "
                f"slug '{body.slug}' already exists."
            ),
        )


@router.patch("/domains/{domain_id}", status_code=200)
async def patch_domain(
    domain_id: int,
    body: DomainPatch,
    caller: ApiKeyRow = Depends(require_auth),
) -> dict:
    """Update a domain; caller must own it or be an admin."""
    try:
        return update(domain_id, body, caller)
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail="You do not own this domain.",
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Domain not found.")
    except DuplicateError:
        raise HTTPException(
            status_code=409,
            detail="A domain with that name or slug already exists.",
        )
