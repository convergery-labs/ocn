"""Domain data models and database access functions."""
from typing import Optional

from db import get_db


def get_domain_configs() -> dict[str, dict]:
    """Load all domain configs (name + taxonomy) from the database.

    Returns:
        Dict mapping domain slug to
        ``{"name": str, "taxonomy": list[str]}``.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT d.slug, d.name, t.category
            FROM   domains    d
            JOIN   taxonomies t ON t.domain_id = d.id
            ORDER  BY d.id, t.position
            """
        ).fetchall()

    configs: dict[str, dict] = {}
    for row in rows:
        slug = row["slug"]
        if slug not in configs:
            configs[slug] = {"name": row["name"], "taxonomy": []}
        configs[slug]["taxonomy"].append(row["category"])
    return configs


def list_domains() -> list[dict]:
    """Return all domains ordered by id."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM domains ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def insert_domain(
    name: str,
    slug: str,
    description: Optional[str],
) -> int:
    """Insert a domain and return its id.

    When called inside a ``transaction()`` block the ambient connection
    is used, so the insert participates in the outer transaction.

    Raises:
        sqlite3.IntegrityError: if name or slug already exists.
    """
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO domains (name, slug, description)"
            " VALUES (?, ?, ?)",
            (name, slug, description),
        )
        return cursor.lastrowid


def get_domain_by_id(domain_id: int) -> dict:
    """Return a single domain row by id.

    Participates in an ambient ``transaction()`` if one is active.
    """
    with get_db() as conn:
        return dict(
            conn.execute(
                "SELECT * FROM domains WHERE id = ?",
                (domain_id,),
            ).fetchone()
        )
