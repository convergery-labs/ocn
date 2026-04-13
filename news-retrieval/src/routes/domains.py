"""Routes for /domains."""
from fastapi import APIRouter, HTTPException

from controllers.domains import DomainIn, create, get_all
from db import DuplicateError

router = APIRouter()


@router.get("/domains")
async def get_domains() -> list[dict]:
    """Return all domains."""
    return get_all()


@router.post("/domains", status_code=201)
async def post_domain(body: DomainIn) -> dict:
    """Create a domain and its taxonomy in a single operation."""
    try:
        return create(body)
    except DuplicateError:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A domain with name '{body.name}' or "
                f"slug '{body.slug}' already exists."
            ),
        )
