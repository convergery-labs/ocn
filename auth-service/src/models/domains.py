"""Domain data models and database access functions."""
from typing import TypedDict

from db import get_db

__all__ = [
    "DomainRow",
    "get_domains_by_slugs",
    "get_domain_slugs_for_user",
    "attach_domains_to_user",
]


class DomainRow(TypedDict):
    """A row from the domains table."""

    id: int
    slug: str


def get_domains_by_slugs(slugs: list[str]) -> list[DomainRow]:
    """Return domain rows matching *slugs* (order not guaranteed)."""
    if not slugs:
        return []
    placeholders = ", ".join("?" * len(slugs))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM domains WHERE slug IN ({placeholders})",
            tuple(slugs),
        ).fetchall()
    return [dict(r) for r in rows]  # type: ignore[return-value]


def get_domain_slugs_for_user(user_id: int) -> list[str]:
    """Return domain slugs assigned to *user_id*."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT d.slug FROM domains d"
            " JOIN user_domains ud ON ud.domain_id = d.id"
            " WHERE ud.user_id = ?",
            (user_id,),
        ).fetchall()
    return [r["slug"] for r in rows]


def attach_domains_to_user(
    user_id: int, domain_ids: list[int]
) -> None:
    """Insert rows into user_domains for each domain id."""
    if not domain_ids:
        return
    with get_db() as conn:
        for domain_id in domain_ids:
            conn.execute(
                "INSERT INTO user_domains (user_id, domain_id)"
                " VALUES (?, ?)",
                (user_id, domain_id),
            )
