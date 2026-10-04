"""Companies API routes."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import models.company as company_model
from auth import get_current_user, get_optional_user

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

    # Market profile. Null on every row that predates it, which is most
    # of the catalogue - absence means "not researched", never zero.
    local_code: str | None = None
    local_name: str | None = None
    search_query: str | None = None
    aliases: list[str] = []
    exclude_terms: list[str] = []
    fiscal_year_end: str | None = None
    market_cap_usd_bn: float | None = None
    market_cap_local: float | None = None
    local_currency: str | None = None
    index_name: str | None = None
    index_weight_pct: float | None = None
    home_market_rank: int | None = None
    domestic_sales_pct: float | None = None
    financials_period: str | None = None
    market_data_as_of: date | None = None
    # Present only when the caller asks for include_customers; None and
    # [] are different answers - None means "not requested", [] means
    # "requested, and this company has none researched".
    customers: list["CompanyCustomer"] | None = None


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

    # Market profile - null on every row loaded before this existed, which
    # is most of the catalogue. A consumer must treat absence as "not
    # researched for this company", never as zero.
    local_code: str | None = None
    local_name: str | None = None
    search_query: str | None = None
    aliases: list[str] = []
    exclude_terms: list[str] = []
    fiscal_year_end: str | None = None
    market_cap_usd_bn: float | None = None
    market_cap_local: float | None = None
    local_currency: str | None = None
    index_name: str | None = None
    index_weight_pct: float | None = None
    home_market_rank: int | None = None
    domestic_sales_pct: float | None = None
    financials_period: str | None = None
    market_data_as_of: date | None = None


class CompanyCustomer(BaseModel):
    """One disclosed counterparty of one tracked company."""
    customer_name: str
    customer_ticker: str | None = None
    aliases: list[str] = []
    relationship: str
    # None means NOT DISCLOSED, never zero: a Japanese issuer need only
    # name a customer once it passes 10% of sales, so a missing figure
    # says nobody crossed the threshold - not that nobody looked.
    pct_of_sales: float | None = None
    period: str | None = None


class VerifyRequest(BaseModel):
    pass  # user identity comes from the bearer token


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #

@router.get("", response_model=list[CompanyBrief])
def list_companies(
    status: str | None = Query(default=None, description="Filter by status: 'verified' or 'pending_review'"),
    country: str | None = Query(default=None, description="Filter by country, e.g. 'United States' (aliases like 'US'/'USA' accepted)"),
    has_ticker: bool | None = Query(default=None, description="true = exclude private (ticker='Private') companies; false = only private companies"),
    tracked: bool | None = Query(default=None, description="true = only companies a signal pipeline follows (those with a local_code). Narrower than country: Japan has 62 catalogue companies but 19 tracked ones."),
    include_customers: bool = Query(default=False, description="Nest each company's disclosed customers and counterparties."),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    _user: dict | None = Depends(get_optional_user),
) -> list[dict[str, Any]]:
    """Return all companies. Auth optional — public read access allowed."""
    return company_model.list_companies(
        status=status, country=country, has_ticker=has_ticker,
        tracked=tracked, include_customers=include_customers,
        limit=limit, offset=offset,
    )


@router.get("/count")
def count() -> dict:
    """Return total company count. Public."""
    stats = company_model.get_stats()
    return {"total": stats["total"], "verified": stats["verified"], "pending": stats["pending"]}


@router.get("/stats")
def stats(_user: dict = Depends(get_current_user)) -> dict:
    """Return total, verified, and pending company counts."""
    return company_model.get_stats()


@router.get("/search", response_model=list[CompanyBrief])
def search(
    q: str = Query(..., min_length=1, description="Company name or ticker"),
    limit: int = Query(10, ge=1, le=50),
    _user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Fuzzy search companies by name or exact ticker match."""
    return company_model.search_companies(q, limit)


@router.get("/pending", response_model=list[CompanyDetail])
def pending(
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    _user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Return pending_review companies. Paginated - default 100 per page."""
    return company_model.get_pending_companies(limit=limit, offset=offset)


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: str, _user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return full company profile by ID."""
    company = company_model.get_company(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.get("/{company_id}/customers", response_model=list[CompanyCustomer])
def get_company_customers(
    company_id: str, _user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Return a company's disclosed customers and other counterparties.

    An empty list means no counterparties have been researched for this
    company - not that it has none. Only the tracked non-US universes
    carry this data today.
    """
    if not company_model.get_company(company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    return company_model.get_company_customers(company_id)


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
