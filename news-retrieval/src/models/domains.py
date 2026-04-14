"""Domain data models and database access functions."""
from datetime import datetime
from typing import Optional, TypedDict

from db import get_db


class DomainRow(TypedDict):
    """A row from the domains table."""

    id: int
    name: str
    slug: str
    description: Optional[str]
    created_at: datetime


class DomainConfig(TypedDict):
    """Domain name and ordered taxonomy for pipeline use."""

    name: str
    taxonomy: list[str]


def get_domain_config(slug: str) -> Optional[DomainConfig]:
    """Load config (name + taxonomy) for a single domain slug.

    Uses a LEFT JOIN so a domain with no taxonomy categories is
    returned as ``{"name": ..., "taxonomy": []}`` rather than
    ``None``, preserving the distinction between an unknown slug
    and a domain that simply has no categories yet.

    Returns:
        ``DomainConfig``, or ``None`` if the slug does not exist.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT d.name, t.category
            FROM   domains         d
            LEFT JOIN taxonomies   t ON t.domain_id = d.id
            WHERE  d.slug = ?
            ORDER  BY t.position
            """,
            (slug,),
        ).fetchall()
    if not rows:
        return None
    return {
        "name": rows[0]["name"],
        "taxonomy": [
            r["category"]
            for r in rows
            if r["category"] is not None
        ],
    }  # type: ignore[return-value]


def list_domains() -> list[DomainRow]:
    """Return all domains ordered by id."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM domains ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]  # type: ignore[return-value]


def insert_domain(
    name: str,
    slug: str,
    description: Optional[str],
) -> int:
    """Insert a domain and return its id.

    When called inside a ``transaction()`` block the ambient connection
    is used, so the insert participates in the outer transaction.

    Raises:
        DuplicateError: if name or slug already exists.
    """
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO domains (name, slug, description)"
            " VALUES (?, ?, ?) RETURNING id",
            (name, slug, description),
        )
        return cursor.fetchone()["id"]


def get_domain_by_id(domain_id: int) -> DomainRow:
    """Return a single domain row by id.

    Participates in an ambient ``transaction()`` if one is active.
    """
    with get_db() as conn:
        return dict(  # type: ignore[return-value]
            conn.execute(
                "SELECT * FROM domains WHERE id = ?",
                (domain_id,),
            ).fetchone()
        )
