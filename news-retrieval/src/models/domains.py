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
    created_by: Optional[int]
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
    created_by: Optional[int] = None,
) -> int:
    """Insert a domain and return its id.

    Raises:
        DuplicateError: if name or slug already exists.
    """
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO domains (name, slug, description, created_by)"
            " VALUES (?, ?, ?, ?) RETURNING id",
            (name, slug, description, created_by),
        )
        return cursor.fetchone()["id"]


def update_domain(
    domain_id: int,
    name: Optional[str],
    slug: Optional[str],
    description: Optional[str],
) -> DomainRow:
    """Update mutable fields of a domain and return the updated row.

    Only non-``None`` arguments are applied.

    Raises:
        DuplicateError: if the new name or slug conflicts.
        ValueError: if the domain does not exist.
    """
    fields = []
    params: list = []
    if name is not None:
        fields.append("name = ?")
        params.append(name)
    if slug is not None:
        fields.append("slug = ?")
        params.append(slug)
    if description is not None:
        fields.append("description = ?")
        params.append(description)
    if not fields:
        return get_domain_by_id(domain_id)
    params.append(domain_id)
    with get_db() as conn:
        row = conn.execute(
            f"UPDATE domains SET {', '.join(fields)}"
            " WHERE id = ? RETURNING *",
            tuple(params),
        ).fetchone()
    if row is None:
        raise ValueError(f"Domain {domain_id} not found.")
    return dict(row)  # type: ignore[return-value]


def get_domain_by_id(domain_id: int) -> DomainRow:
    """Return a single domain row by id."""
    with get_db() as conn:
        return dict(  # type: ignore[return-value]
            conn.execute(
                "SELECT * FROM domains WHERE id = ?",
                (domain_id,),
            ).fetchone()
        )
