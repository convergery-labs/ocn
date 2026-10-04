"""DB query functions for universe_companies."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db import get_db

# Aliases -> canonical country name. Keys are matched case-insensitively
# after stripping whitespace.
_COUNTRY_ALIASES = {
    "usa": "United States",
    "u.s.a.": "United States",
    "u.s.": "United States",
    "us": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
}


def normalize_country(country: str | None) -> str | None:
    """Map known country aliases (USA, UK, ...) to their canonical name."""
    if not country:
        return country
    return _COUNTRY_ALIASES.get(country.strip().lower(), country)


# Subquery fragments reused across queries
_CATEGORY_NAMES = """
    COALESCE((SELECT array_agg(name ORDER BY name)
     FROM universe_taxonomy WHERE id = ANY(c.category_ids)), '{}')
"""
_SUBCATEGORY_NAMES = """
    COALESCE((SELECT array_agg(name ORDER BY name)
     FROM universe_taxonomy WHERE id = ANY(COALESCE(c.subcategory_ids, '{}'))), '{}')
"""
_PROPOSED_SUBCATEGORY_NAMES = """
    COALESCE((SELECT array_agg(name ORDER BY name)
     FROM universe_taxonomy
     WHERE id = ANY(COALESCE(c.subcategory_ids, '{}')) AND agent_proposed = TRUE), '{}')
"""

_DETAIL_COLS = f"""
    c.id::text, c.company_name, c.ticker, c.market, c.country, c.website,
    c.multi_category_reason, c.status, c.agent_added,
    c.added_by, c.added_at, c.verified_by, c.verified_at,
    c.local_code, c.local_name, c.search_query,
    COALESCE(c.aliases, '{{}}') AS aliases,
    COALESCE(c.exclude_terms, '{{}}') AS exclude_terms,
    c.fiscal_year_end, c.market_cap_usd_bn, c.market_cap_local,
    c.local_currency, c.index_name, c.index_weight_pct,
    c.home_market_rank, c.domestic_sales_pct, c.financials_period,
    c.market_data_as_of,
    {_CATEGORY_NAMES} AS categories,
    {_SUBCATEGORY_NAMES} AS subcategories,
    {_PROPOSED_SUBCATEGORY_NAMES} AS proposed_subcategories
"""

# The market-profile columns are carried on the BRIEF projection too,
# not just the detail one. The signal pipelines read their whole tracked
# universe in a single listing call; without these here they would have
# to follow up with one authenticated detail fetch per company, turning
# one request into twenty. They are NULL on the ~1,400 rows that predate
# this, which costs those callers nothing.
_BRIEF_COLS = f"""
    c.id::text, c.company_name, c.ticker, c.market, c.country, c.website,
    c.status, c.agent_added, c.added_at,
    c.local_code, c.local_name, c.search_query,
    COALESCE(c.aliases, '{{}}') AS aliases,
    COALESCE(c.exclude_terms, '{{}}') AS exclude_terms,
    c.fiscal_year_end, c.market_cap_usd_bn, c.market_cap_local,
    c.local_currency, c.index_name, c.index_weight_pct,
    c.home_market_rank, c.domestic_sales_pct, c.financials_period,
    c.market_data_as_of,
    {_CATEGORY_NAMES} AS categories,
    {_SUBCATEGORY_NAMES} AS subcategories,
    {_PROPOSED_SUBCATEGORY_NAMES} AS proposed_subcategories
"""


def get_stats() -> dict[str, int]:
    """Return total, verified, and pending company counts."""
    with get_db() as conn:
        cur = conn.execute("""
            SELECT
                COUNT(*)                                          AS total,
                COUNT(*) FILTER (WHERE status = 'verified')      AS verified,
                COUNT(*) FILTER (WHERE status = 'pending_review') AS pending
            FROM universe_companies
        """)
        row = cur.fetchone()
        return {"total": row["total"], "verified": row["verified"], "pending": row["pending"]}


def search_companies(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fuzzy search on company_name (pg_trgm) + exact ticker match.

    Returns results ordered by: ticker exact match first, then similarity desc.
    Includes a match_score (0–1) so callers can apply confidence thresholds.
    """
    with get_db() as conn:
        cur = conn.execute(
            f"""
            SELECT {_BRIEF_COLS},
                   GREATEST(
                       word_similarity(LOWER(:query), LOWER(c.company_name)),
                       CASE WHEN LOWER(c.ticker) = LOWER(:query) THEN 1.0 ELSE 0.0 END
                   ) AS match_score
            FROM universe_companies c
            WHERE word_similarity(LOWER(:query), LOWER(c.company_name)) > 0.2
               OR c.company_name ILIKE '%%' || :query || '%%'
               OR LOWER(c.ticker) = LOWER(:query)
            ORDER BY
                CASE WHEN LOWER(c.ticker) = LOWER(:query) THEN 1 ELSE 0 END DESC,
                word_similarity(LOWER(:query), LOWER(c.company_name)) DESC
            LIMIT :limit
            """,
            {"query": query, "limit": limit},
        )
        return [dict(r) for r in cur.fetchall()]


def get_company(company_id: str) -> dict[str, Any] | None:
    """Return full company profile by UUID, or None if not found."""
    with get_db() as conn:
        cur = conn.execute(
            f"SELECT {_DETAIL_COLS} FROM universe_companies c WHERE c.id = :id",
            {"id": company_id},
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_company_customers(company_id: str) -> list[dict[str, Any]]:
    """Return one company's disclosed counterparties, largest first.

    Ordered with the disclosed percentages at the top because they are the
    only ones carrying a filed figure; the rest are named relationships
    with no size attached, and NULLS LAST keeps them from displacing the
    ones that do.
    """
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            """
            SELECT customer_name, customer_ticker, aliases, relationship,
                   pct_of_sales, period
              FROM universe_company_customers
             WHERE company_id = :id
             ORDER BY pct_of_sales DESC NULLS LAST, customer_name
            """,
            {"id": company_id},
        ).fetchall()]


def list_companies(
    status: str | None = None,
    country: str | None = None,
    has_ticker: bool | None = None,
    tracked: bool | None = None,
    include_customers: bool = False,
    limit: int = 5000,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return companies, optionally filtered by status, country, and ticker presence. Ordered by company_name.

    ``tracked`` selects the companies a signal pipeline actually follows,
    identified by having a local_code. Country alone is not the same
    question and will not do: Japan holds 62 catalogue companies but only
    19 tracked ones, so a consumer filtering on country would try to
    fetch filings for Keyence and Daikin.

    ``include_customers`` nests each company's disclosed counterparties.
    Off by default and deliberately opt-in - only the Japan classifier
    reads them, and switching it on by default would make every caller
    pay for a join none of the other ~1,400 rows has data for.
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    where = "WHERE c.ticker != ''"
    if status:
        where += " AND c.status = :status"
        params["status"] = status
    if country:
        where += " AND c.country ILIKE :country"
        params["country"] = normalize_country(country)
    if has_ticker is True:
        where += " AND c.ticker != 'Private'"
    elif has_ticker is False:
        where += " AND c.ticker = 'Private'"
    if tracked is True:
        where += " AND c.local_code IS NOT NULL"
    elif tracked is False:
        where += " AND c.local_code IS NULL"
    with get_db() as conn:
        cur = conn.execute(
            f"""
            SELECT {_BRIEF_COLS}
            FROM universe_companies c
            {where}
            ORDER BY c.company_name ASC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )
        rows = [dict(r) for r in cur.fetchall()]

        if include_customers and rows:
            # One query for every company on the page, grouped in memory,
            # rather than a query per row.
            by_company: dict[str, list[dict[str, Any]]] = {}
            for cust in conn.execute(
                """
                SELECT company_id::text AS company_id, customer_name,
                       customer_ticker, aliases, relationship,
                       pct_of_sales, period
                  FROM universe_company_customers
                 -- ::uuid[] because _BRIEF_COLS selects id::text, so the
                 -- ids arriving here are strings and Postgres will not
                 -- compare text to uuid on its own.
                 WHERE company_id = ANY(:ids::uuid[])
                 ORDER BY pct_of_sales DESC NULLS LAST, customer_name
                """,
                {"ids": [r["id"] for r in rows]},
            ).fetchall():
                c = dict(cust)
                by_company.setdefault(c.pop("company_id"), []).append(c)
            for r in rows:
                r["customers"] = by_company.get(r["id"], [])

        return rows


def get_pending_companies(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Return pending_review companies, newest first. Paginated - default page size 100."""
    with get_db() as conn:
        cur = conn.execute(
            f"""
            SELECT {_DETAIL_COLS}
            FROM universe_companies c
            WHERE c.status = 'pending_review'
            ORDER BY c.added_at DESC
            LIMIT :limit OFFSET :offset
            """,
            {"limit": limit, "offset": offset},
        )
        return [dict(r) for r in cur.fetchall()]


def count_pending_companies() -> int:
    """Return total count of pending_review companies."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM universe_companies WHERE status = 'pending_review'"
        )
        return cur.fetchone()[0]


def verify_company(company_id: str, verified_by: str) -> bool:
    """Flip status → verified. Returns True if a row was updated."""
    now = datetime.now(timezone.utc)
    with get_db() as conn:
        cur = conn.execute(
            """
            UPDATE universe_companies
               SET status = 'verified',
                   verified_by = :verified_by,
                   verified_at = :verified_at
             WHERE id = :id
               AND status = 'pending_review'
            """,
            {"id": company_id, "verified_by": verified_by, "verified_at": now},
        )
        return cur.rowcount == 1


def get_companies_by_category_id(category_id: int) -> list[dict[str, Any]]:
    """Return all companies in a given category (name + ticker only - for discovery dedup)."""
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT company_name, ticker
            FROM universe_companies
            WHERE :cat_id = ANY(category_ids)
            ORDER BY company_name
            """,
            {"cat_id": category_id},
        )
        return [dict(r) for r in cur.fetchall()]


def create_company(fields: dict[str, Any]) -> dict[str, Any]:
    """Insert a new company row. Returns the created record."""
    fields.setdefault("subcategory_ids", [])
    fields.setdefault("category_ids", [])
    if "country" in fields:
        fields["country"] = normalize_country(fields["country"])
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO universe_companies (
                company_name, ticker, market, country, website,
                category_ids, subcategory_ids, multi_category_reason,
                status, agent_added, added_by
            ) VALUES (
                :company_name, :ticker, :market, :country, :website,
                :category_ids, :subcategory_ids, :multi_category_reason,
                'pending_review', TRUE, :added_by
            )
            RETURNING id::text
            """,
            fields,
        )
        new_id = cur.fetchone()["id"]
    return get_company(new_id)


def update_company(company_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """Update any subset of editable fields. Returns updated record or None."""
    allowed = {
        "company_name", "ticker", "market", "country", "website",
        "category_ids", "subcategory_ids", "multi_category_reason",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if "country" in updates:
        updates["country"] = normalize_country(updates["country"])
    if updates.get("subcategory_ids") is None:
        updates["subcategory_ids"] = []
    if updates.get("category_ids") is None:
        updates["category_ids"] = []
    if not updates:
        return get_company(company_id)

    set_clause = ", ".join(f"{col} = :{col}" for col in updates)
    updates["id"] = company_id

    with get_db() as conn:
        conn.execute(
            f"UPDATE universe_companies SET {set_clause} WHERE id = :id",
            updates,
        )
    return get_company(company_id)
