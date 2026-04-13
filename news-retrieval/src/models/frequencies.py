"""Frequency data models and database access functions."""
from pydantic import BaseModel, Field

from db import get_db


class FrequencyIn(BaseModel):
    """Request body for POST /frequencies."""

    name: str
    min_days_back: int = Field(ge=1)


def list_frequencies() -> list[dict]:
    """Return all frequencies ordered by min_days_back."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM frequencies ORDER BY min_days_back"
        ).fetchall()
    return [dict(r) for r in rows]


def create_frequency(body: FrequencyIn) -> dict:
    """Insert a new frequency and return the created row.

    Raises:
        DuplicateError: if name already exists.
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO frequencies (name, min_days_back)
            VALUES (:name, :min_days_back)
            RETURNING id
            """,
            body.model_dump(),
        )
        new_id = cursor.fetchone()["id"]
        row = conn.execute(
            "SELECT * FROM frequencies WHERE id = ?",
            (new_id,),
        ).fetchone()
    return dict(row)
