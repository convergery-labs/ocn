"""DB query functions for universe_companies."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db import get_db

# Subquery fragments reused across queries
_CATEGORY_NAMES = """
    (SELECT array_agg(name ORDER BY name)
     FROM universe_taxonomy WHERE id = ANY(c.category_ids))
"""
_SUBCATEGORY_NAMES = """
    (SELECT array_agg(name ORDER BY name)
     FROM universe_taxonomy WHERE id = ANY(c.subcategory_ids))
"""
_PROPOSED_SUBCATEGORY_NAMES = """
    (SELECT array_agg(name ORDER BY name)
     FROM universe_taxonomy
     WHERE id = ANY(c.subcategory_ids) AND agent_proposed = TRUE)
"""

_DETAIL_COLS = f"""
    c.id::text, c.company_name, c.ticker, c.market, c.country, c.website,
    c.multi_category_reason, c.status, c.agent_added,
    c.added_by, c.added_at, c.verified_by, c.verified_at,
    {_CATEGORY_NAMES} AS categories,
    {_SUBCATEGORY_NAMES} AS subcategories,
    {_PROPOSED_SUBCATEGORY_NAMES} AS proposed_subcategories
"""

_BRIEF_COLS = f"""
    c.id::text, c.company_name, c.ticker, c.market, c.country, c.website,
    c.status, c.agent_added, c.added_at,
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
