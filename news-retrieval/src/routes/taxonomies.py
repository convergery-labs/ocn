"""Routes for /taxonomies."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import DuplicateError
from models.taxonomies import TaxonomyIn, create_taxonomy, list_taxonomies

router = APIRouter()


@router.get("/taxonomies")
async def get_taxonomies(
    domain: Optional[str] = Query(default=None),
) -> list[dict]:
    """Return all taxonomy categories, optionally filtered by domain."""
    return list_taxonomies(domain)


@router.post("/taxonomies", status_code=201)
async def post_taxonomy(body: TaxonomyIn) -> dict:
    """Add a category to a domain's taxonomy."""
    try:
        return create_taxonomy(body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DuplicateError:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Category '{body.category}' already exists "
                f"for domain_id {body.domain_id}."
            ),
        )
