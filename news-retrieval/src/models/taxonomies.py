"""Taxonomy data models and database access functions."""
from typing import Optional

from pydantic import BaseModel, Field

from db import get_db


class TaxonomyIn(BaseModel):
    """Request body for POST /taxonomies."""

    domain_id: int
    category: str
    position: Optional[int] = Field(
        default=None,
        description=(
            "Display order within the domain. "
            "Defaults to max(position) + 1 for the domain."
        ),
    )


def list_taxonomies(domain: Optional[str] = None) -> list[dict]:
    """Return all taxonomy categories, optionally filtered by domain."""
    with get_db() as conn:
        if domain:
            rows = conn.execute(
                """
                SELECT t.*, d.slug AS domain_slug
                FROM   taxonomies t
                JOIN   domains    d ON d.id = t.domain_id
                WHERE  d.slug = ?
                ORDER  BY t.position
                """,
                (domain,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT t.*, d.slug AS domain_slug
                FROM   taxonomies t
                JOIN   domains    d ON d.id = t.domain_id
                ORDER  BY d.id, t.position
                """
            ).fetchall()
    return [dict(r) for r in rows]


def create_taxonomy(body: TaxonomyIn) -> dict:
    """Insert a new taxonomy category and return the created row.

    Auto-assigns position as ``MAX(position) + 1`` when omitted.

    Raises:
        ValueError: if domain_id not found.
        DuplicateError: if category already exists for domain.
    """
    with get_db() as conn:
        if not conn.execute(
            "SELECT id FROM domains WHERE id = ?", (body.domain_id,)
        ).fetchone():
            raise ValueError(
                f"domain_id {body.domain_id} not found."
            )
        position = body.position
        if position is None:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), 0) AS m "
                "FROM taxonomies WHERE domain_id = ?",
                (body.domain_id,),
            ).fetchone()
            position = row["m"] + 1
        cursor = conn.execute(
            "INSERT INTO taxonomies (domain_id, category, position)"
            " VALUES (:domain_id, :category, :position)"
            " RETURNING id",
            {
                "domain_id": body.domain_id,
                "category": body.category,
                "position": position,
            },
        )
        new_id = cursor.fetchone()["id"]
        row = conn.execute(
            "SELECT t.*, d.slug AS domain_slug "
            "FROM taxonomies t "
            "JOIN domains d ON d.id = t.domain_id "
            "WHERE t.id = ?",
            (new_id,),
        ).fetchone()
    return dict(row)


def insert_taxonomy(
    domain_id: int,
    category: str,
    position: int,
) -> int:
    """Insert a taxonomy entry and return its id.

    When called inside a ``transaction()`` block the ambient connection
    is used, so the insert participates in the outer transaction.

    Raises:
        DuplicateError: if category already exists for domain.
    """
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO taxonomies (domain_id, category, position)"
            " VALUES (?, ?, ?) RETURNING id",
            (domain_id, category, position),
        )
        return cursor.fetchone()["id"]


def list_by_domain_id(domain_id: int) -> list[dict]:
    """Return taxonomy rows for a domain, ordered by position.

    Participates in an ambient ``transaction()`` if one is active.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT t.*, d.slug AS domain_slug
            FROM   taxonomies t
            JOIN   domains    d ON d.id = t.domain_id
            WHERE  t.domain_id = ?
            ORDER  BY t.position
            """,
            (domain_id,),
        ).fetchall()
    return [dict(r) for r in rows]
