"""DB query functions for universe_scan_jobs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from db import get_db


def has_running_job() -> bool:
    """Return True if any scan job is currently running."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT 1 FROM universe_scan_jobs WHERE status = 'running' LIMIT 1"
        )
        return cur.fetchone() is not None


def create(category_ids: list[int], triggered_by: str) -> str:
    """Insert a new scan job row and return its UUID."""
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO universe_scan_jobs (categories_total, triggered_by)
            VALUES (:total, :triggered_by)
            RETURNING id::text
            """,
            {"total": len(category_ids), "triggered_by": triggered_by},
        )
        return cur.fetchone()["id"]


def get(job_id: str) -> dict[str, Any] | None:
    """Return full job record or None."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT id::text, * FROM universe_scan_jobs WHERE id = :id",
            {"id": job_id},
        )
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        # Rename id → job_id for the API response
        d["job_id"] = str(d.pop("id"))
        results = d.get("category_results", [])
        d["category_results"] = results if isinstance(results, list) else json.loads(results)
        return d


def append_category_result(
    job_id: str,
    category_id: int,
    category_name: str,
    proposed: int,
    skipped: int,
    status: str = "completed",
) -> None:
    """Append one category result and update running totals."""
    entry = {
        "category_id": category_id,
        "category_name": category_name,
        "status": status,
        "proposed": proposed,
        "skipped": skipped,
    }
    with get_db() as conn:
        conn.execute(
            """
            UPDATE universe_scan_jobs
               SET categories_done     = categories_done + 1,
                   companies_proposed  = companies_proposed + :proposed,
                   companies_skipped   = companies_skipped + :skipped,
                   category_results    = category_results || :entry::jsonb
             WHERE id = :id
            """,
            {
                "id": job_id,
                "proposed": proposed,
                "skipped": skipped,
                "entry": json.dumps(entry),
            },
        )


def get_last_run_at() -> str | None:
    """Return completed_at of the most recently completed scan job, or None."""
    with get_db() as conn:
        cur = conn.execute(
            """
            SELECT completed_at
            FROM universe_scan_jobs
            WHERE status = 'completed'
            ORDER BY completed_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return row["completed_at"].isoformat() if row and row["completed_at"] else None


def mark_complete(job_id: str, status: str = "completed") -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE universe_scan_jobs
               SET status       = :status,
                   completed_at = :now
             WHERE id = :id
            """,
            {"id": job_id, "status": status, "now": datetime.now(timezone.utc)},
        )
