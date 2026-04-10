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
        sqlite3.IntegrityError: if name already exists.
    """
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO frequencies (name, min_days_back)
            VALUES (:name, :min_days_back)
            """,
            body.model_dump(),
        )
        row = conn.execute(
            "SELECT * FROM frequencies WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)
