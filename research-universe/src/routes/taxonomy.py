"""Taxonomy API routes."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import models.taxonomy as taxonomy_model
from db import DuplicateError

router = APIRouter(prefix="/taxonomy", tags=["taxonomy"])


# --------------------------------------------------------------------------- #
# Pydantic schemas                                                             #
# --------------------------------------------------------------------------- #

class TaxonomyEntry(BaseModel):
    id: int
    type: str
    name: str
    parent_id: int | None = None
    agent_proposed: bool
    created_by: str | None = None
    created_at: datetime | None = None
    match_score: float | None = None


class CategoryEntry(BaseModel):
    id: int
    name: str
    agent_proposed: bool
    created_by: str | None = None
    created_at: datetime | None = None


class SubcategoryEntry(BaseModel):
    id: int
    name: str
    parent_id: int
    agent_proposed: bool
    created_by: str | None = None
    created_at: datetime | None = None


class CreateCategoryRequest(BaseModel):
    name: str
    created_by: str


class CreateSubcategoryRequest(BaseModel):
    name: str
    category_id: int
    created_by: str


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #

@router.get("/categories", response_model=list[CategoryEntry])
def list_categories() -> list[dict[str, Any]]:
    """List all 19 (+ any agent-proposed) categories."""
    return taxonomy_model.list_categories()


@router.get("/subcategories", response_model=list[SubcategoryEntry])
def list_subcategories(
    category_id: int = Query(..., description="Parent category ID"),
) -> list[dict[str, Any]]:
    """List all subcategories for a given category."""
    return taxonomy_model.list_subcategories(category_id)


@router.get("/search", response_model=list[TaxonomyEntry])
def search(
    q: str = Query(..., min_length=1, description="Taxonomy name to search"),
    limit: int = Query(5, ge=1, le=20),
) -> list[dict[str, Any]]:
    """Fuzzy search across all taxonomy entries.

    Used for dedup check before creating a new subcategory or category.
    """
    return taxonomy_model.search_taxonomy(q, limit)


@router.post("/categories", response_model=CategoryEntry, status_code=201)
def create_category(body: CreateCategoryRequest) -> dict[str, Any]:
    """Create a new category (agent_proposed=true)."""
    try:
        return taxonomy_model.create_category(body.name, body.created_by)
    except DuplicateError:
        raise HTTPException(
            status_code=409,
            detail=f"Category '{body.name}' already exists",
        )


@router.post("/subcategories", response_model=SubcategoryEntry, status_code=201)
def create_subcategory(body: CreateSubcategoryRequest) -> dict[str, Any]:
    """Create a new subcategory under an existing category (agent_proposed=true)."""
    try:
        return taxonomy_model.create_subcategory(
            body.name, body.category_id, body.created_by
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DuplicateError:
        raise HTTPException(
            status_code=409,
            detail=f"Subcategory '{body.name}' already exists",
        )
