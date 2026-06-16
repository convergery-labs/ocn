"""Companies API routes."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import models.company as company_model
from auth import get_current_user

router = APIRouter(prefix="/companies", tags=["companies"])


# --------------------------------------------------------------------------- #
# Pydantic schemas                                                             #
# --------------------------------------------------------------------------- #

class CompanyBrief(BaseModel):
    id: str
    company_name: str
    ticker: str
    market: str
    country: str
    status: str
    agent_added: bool
    added_at: datetime
    categories: list[str] = []
    subcategories: list[str] = []
    match_score: float | None = None


class CompanyDetail(BaseModel):
    id: str
    company_name: str
    ticker: str
    market: str
    country: str
    website: str
    multi_category_reason: str | None = None
    status: str
    agent_added: bool
    added_by: str | None = None
    added_at: datetime
    verified_by: str | None = None
    verified_at: datetime | None = None
    categories: list[str] = []
    subcategories: list[str] = []
    proposed_subcategories: list[str] = []


class VerifyRequest(BaseModel):
    pass  # user identity comes from the bearer token


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #

@router.get("", response_model=list[CompanyBrief])
def list_companies(
    status: str | None = Query(default=None, description="Filter by status: 'verified' or 'pending_review'"),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """Return all companies with tickers, optionally filtered by status."""
    return company_model.list_companies(status=status, limit=limit, offset=offset)


@router.get("/stats")
def stats() -> dict:
    """Return total, verified, and pending company counts."""
    return company_model.get_stats()


@router.get("/search", response_model=list[CompanyBrief])
def search(
    q: str = Query(..., min_length=1, description="Company name or ticker"),
    limit: int = Query(10, ge=1, le=50),
) -> list[dict[str, Any]]:
    """Fuzzy search companies by name or exact ticker match."""
    return company_model.search_companies(q, limit)


@router.get("/pending", response_model=list[CompanyDetail])
def pending(
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """Return pending_review companies. Paginated - default 100 per page."""
    return company_model.get_pending_companies(limit=limit, offset=offset)


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: str) -> dict[str, Any]:
    """Return full company profile by ID."""
    company = company_model.get_company(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.post("/{company_id}/verify", response_model=CompanyDetail)
def verify(
    company_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Flip a pending_review company to verified."""
    updated = company_model.verify_company(company_id, current_user["name"])
    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Company not found or already verified",
        )
    return company_model.get_company(company_id)
