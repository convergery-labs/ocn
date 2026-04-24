"""Source data models and database access functions."""
from datetime import datetime
from typing import Optional, TypedDict

from pydantic import BaseModel

from db import get_db


class SourceIn(BaseModel):
    """Request body for POST /sources."""

    url: str
    domain_id: int
    frequency_id: int
    name: Optional[str] = None
    description: Optional[str] = None
    no_fetch: bool = False


class SourceBase(TypedDict):
    """A row from the sources table."""

    id: int
    url: str
    domain_id: int
    frequency_id: int
    name: Optional[str]
    description: Optional[str]
    no_fetch: bool
    created_at: datetime


class SourceRow(SourceBase, total=False):
    """A source row joined with domain and frequency names."""

    domain_slug: str
    frequency_name: str


class SourceRef(TypedDict):
    """Minimal source projection used by the pipeline."""

    url: str
    min_days_back: int
    no_fetch: bool


def load_sources(domain_slug: str, days_back: int) -> list[SourceRef]:
    """Return sources for a domain whose frequency qualifies.

    A source qualifies when ``frequency.min_days_back <= days_back``.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT s.url, f.min_days_back, s.no_fetch
            FROM   sources     s
            JOIN   frequencies f ON f.id = s.frequency_id
            JOIN   domains     d ON d.id = s.domain_id
            WHERE  d.slug = ?
              AND  f.min_days_back <= ?
            """,
            (domain_slug, days_back),
        ).fetchall()
    return [dict(r) for r in rows]  # type: ignore[return-value]


def list_sources(domain: Optional[str] = None) -> list[SourceRow]:
    """Return all sources, optionally filtered by domain slug."""
    with get_db() as conn:
        if domain:
            rows = conn.execute(
                """
                SELECT s.*, d.slug AS domain_slug,
                       f.name AS frequency_name
                FROM   sources     s
                JOIN   domains     d ON d.id = s.domain_id
                JOIN   frequencies f ON f.id = s.frequency_id
                WHERE  d.slug = ?
                ORDER  BY s.id
                """,
                (domain,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT s.*, d.slug AS domain_slug,
                       f.name AS frequency_name
                FROM   sources     s
                JOIN   domains     d ON d.id = s.domain_id
                JOIN   frequencies f ON f.id = s.frequency_id
                ORDER  BY s.id
                """
            ).fetchall()
    return [dict(r) for r in rows]  # type: ignore[return-value]


def create_source(body: SourceIn) -> SourceBase:
    """Insert a new source and return the created row.

    Raises:
        ValueError: if domain_id or frequency_id not found.
        DuplicateError: if URL already exists.
    """
    with get_db() as conn:
        if not conn.execute(
            "SELECT id FROM domains WHERE id = ?", (body.domain_id,)
        ).fetchone():
            raise ValueError(
                f"domain_id {body.domain_id} not found."
            )
        if not conn.execute(
            "SELECT id FROM frequencies WHERE id = ?",
            (body.frequency_id,),
        ).fetchone():
            raise ValueError(
                f"frequency_id {body.frequency_id} not found."
            )
        cursor = conn.execute(
            """
            INSERT INTO sources
                (url, domain_id, frequency_id, name, description,
                 no_fetch)
            VALUES
                (:url, :domain_id, :frequency_id, :name, :description,
                 :no_fetch)
            RETURNING id
            """,
            body.model_dump(),
        )
        new_id = cursor.fetchone()["id"]
        row = conn.execute(
            "SELECT * FROM sources WHERE id = ?",
            (new_id,),
        ).fetchone()
    return dict(row)  # type: ignore[return-value]
