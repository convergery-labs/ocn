"""DB query functions for pipeline report records."""
from datetime import datetime
from typing import Optional, TypedDict

from db import get_db


class ReportRow(TypedDict):
    """A row from the reports table."""

    id: int
    run_id: int
    filename: str
    created_at: datetime


def create_report(run_id: int, filename: str) -> int:
    """Insert a report record and return its id."""
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO reports (run_id, filename)
            VALUES (:run_id, :filename)
            RETURNING id
            """,
            {"run_id": run_id, "filename": filename},
        )
        return cur.fetchone()["id"]


def list_reports(run_id: int) -> list[ReportRow]:
    """Return all report records for a run."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM reports WHERE run_id = :run_id"
            " ORDER BY created_at ASC",
            {"run_id": run_id},
        )
        return [dict(r) for r in cur.fetchall()]  # type: ignore[return-value]


def get_report(report_id: int) -> Optional[ReportRow]:
    """Return a single report record by id, or None if not found."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM reports WHERE id = :id",
            {"id": report_id},
        )
        row = cur.fetchone()
        return dict(row) if row else None  # type: ignore[return-value]
