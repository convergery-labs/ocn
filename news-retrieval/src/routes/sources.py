"""Routes for /sources."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import DuplicateError
from models.sources import SourceIn, create_source, list_sources

router = APIRouter()


@router.get("/sources")
async def get_sources(
    domain: Optional[str] = Query(default=None),
) -> list[dict]:
    """Return all sources, optionally filtered by domain slug."""
    return list_sources(domain)


@router.post("/sources", status_code=201)
async def post_source(body: SourceIn) -> dict:
    """Add a new RSS feed source."""
    try:
        return create_source(body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DuplicateError:
        raise HTTPException(
            status_code=409,
            detail=f"URL '{body.url}' already exists.",
        )
