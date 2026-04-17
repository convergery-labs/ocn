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
    """Domain name and description for pipeline use."""

    name: str
    description: Optional[str]


def get_domain_config(slug: str) -> Optional[DomainConfig]:
    """Load config (name + description) for a domain slug.

    Returns:
        ``DomainConfig``, or ``None`` if the slug does not exist.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT name, description FROM domains WHERE slug = ?",
            (slug,),
        ).fetchone()
    if not row:
        return None
    return {
        "name": row["name"],
        "description": row["description"],
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
    """Return a single domain row by id."""
    with get_db() as conn:
        return dict(  # type: ignore[return-value]
            conn.execute(
                "SELECT * FROM domains WHERE id = ?",
                (domain_id,),
            ).fetchone()
        )
