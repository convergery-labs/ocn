"""DB query functions for pipeline run records."""
from datetime import datetime
from typing import Optional, TypedDict

from db import get_db


class RunRow(TypedDict):
    """A row from the runs table."""

    id: int
    name: str
    domain: str
    started_at: datetime
    completed_at: Optional[datetime]
    status: str
    days_back: int
    max_articles: Optional[int]
    summary_depth: str
    focus: Optional[str]
    report_count: Optional[int]
    summary: Optional[str]


def create_run(
    name: str,
    domain: str,
    days_back: int,
    max_articles: Optional[int],
    summary_depth: str,
    focus: Optional[str],
) -> int:
    """Insert a new run record and return its id."""
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO runs
                (name, domain, days_back, max_articles,
                 summary_depth, focus, status)
            VALUES
                (:name, :domain, :days_back, :max_articles,
                 :summary_depth, :focus, 'running')
            RETURNING id
            """,
            {
                "name": name,
                "domain": domain,
                "days_back": days_back,
                "max_articles": max_articles,
                "summary_depth": summary_depth,
                "focus": focus,
            },
        )
        return cur.fetchone()["id"]


def complete_run(
    run_id: int,
    summary: str,
    report_count: int,
) -> None:
    """Mark a run as completed with its result summary."""
    with get_db() as conn:
        conn.execute(
            """
            UPDATE runs
            SET status       = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                summary      = :summary,
                report_count = :report_count
            WHERE id = :id
            """,
            {
                "id": run_id,
                "summary": summary,
                "report_count": report_count,
            },
        )


def fail_run(run_id: int, summary: str) -> None:
    """Mark a run as failed with an error summary."""
    with get_db() as conn:
        conn.execute(
            """
            UPDATE runs
            SET status       = 'failed',
                completed_at = CURRENT_TIMESTAMP,
                summary      = :summary
            WHERE id = :id
            """,
            {"id": run_id, "summary": summary},
        )


def list_runs() -> list[RunRow]:
    """Return all runs ordered newest-first."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]  # type: ignore[return-value]


def get_run(run_id: int) -> Optional[RunRow]:
    """Return a single run by id, or None if not found."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM runs WHERE id = :id",
            {"id": run_id},
        )
        row = cur.fetchone()
        return dict(row) if row else None  # type: ignore[return-value]
