"""DB query functions for universe_taxonomy."""
from __future__ import annotations

from typing import Any

from db import DuplicateError, get_db


def list_categories() -> list[dict[str, Any]]:
    """Return all categories ordered by name."""
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT id, name, agent_proposed, created_by, created_at
            FROM universe_taxonomy
            WHERE type = 'category'
            ORDER BY name
            """
        )
        return [dict(r) for r in cur.fetchall()]


def list_subcategories(category_id: int) -> list[dict[str, Any]]:
    """Return all subcategories for a given category id, ordered by name."""
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT id, name, parent_id, agent_proposed, created_by, created_at
            FROM universe_taxonomy
            WHERE type = 'subcategory' AND parent_id = :category_id
            ORDER BY name
            """,
            {"category_id": category_id},
        )
        return [dict(r) for r in cur.fetchall()]


def search_taxonomy(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Fuzzy search across all taxonomy entries (case-insensitive).

    Used for dedup check before creating a new subcategory or category.
    Returns entries ordered by word_similarity desc.
    """
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT id, type, name, parent_id, agent_proposed,
                   word_similarity(LOWER(:query), LOWER(name)) AS match_score
            FROM universe_taxonomy
            WHERE word_similarity(LOWER(:query), LOWER(name)) > 0.45
               OR name ILIKE '%%' || :query || '%%'
            ORDER BY word_similarity(LOWER(:query), LOWER(name)) DESC
            LIMIT :limit
            """,
            {"query": query, "limit": limit},
        )
        return [dict(r) for r in cur.fetchall()]


def mark_category_enriched(category_id: int) -> None:
    """Stamp last_enriched_at = NOW() on a category after a successful scan."""
    with get_db() as conn:
        conn.execute(
            "UPDATE universe_taxonomy SET last_enriched_at = NOW() WHERE id = :id",
            {"id": category_id},
        )


def get_taxonomy_by_name(name: str, type_: str) -> dict[str, Any] | None:
    """Exact (case-insensitive) lookup of a taxonomy entry by name and type."""
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT id, type, name, parent_id, agent_proposed
            FROM universe_taxonomy
            WHERE type = :type AND LOWER(name) = LOWER(:name)
            LIMIT 1
            """,
            {"type": type_, "name": name},
        )
        row = cur.fetchone()
        return dict(row) if row else None


def create_category(name: str, created_by: str) -> dict[str, Any]:
    """Insert a new category. Raises DuplicateError if name already exists."""
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO universe_taxonomy (type, name, agent_proposed, created_by)
            VALUES ('category', :name, TRUE, :created_by)
            RETURNING id, type, name, parent_id, agent_proposed, created_by, created_at
            """,
            {"name": name, "created_by": created_by},
        )
        return dict(cur.fetchone())


def create_subcategory(
    name: str, category_id: int, created_by: str
) -> dict[str, Any]:
    """Insert a new subcategory under a category.

    Raises DuplicateError if name already exists.
    Raises ValueError if category_id is not a valid category.
    """
    with get_db() as conn:
        # Verify parent exists and is a category
        cur = conn.execute(
            "SELECT id FROM universe_taxonomy WHERE id = :id AND type = 'category'",
            {"id": category_id},
        )
        if not cur.fetchone():
            raise ValueError(f"Category id {category_id} not found")

        cur = conn.execute(
            """
            INSERT INTO universe_taxonomy (type, name, parent_id, agent_proposed, created_by)
            VALUES ('subcategory', :name, :parent_id, TRUE, :created_by)
            RETURNING id, type, name, parent_id, agent_proposed, created_by, created_at
            """,
            {"name": name, "parent_id": category_id, "created_by": created_by},
        )
        return dict(cur.fetchone())
