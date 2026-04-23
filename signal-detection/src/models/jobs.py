"""Repository functions for classification_jobs and classifications."""
import base64
import json
from typing import Any

from db import get_db


class JobRow(dict):
    """Row from classification_jobs."""


class ClassificationRow(dict):
    """Row from classifications."""


def _encode_cursor(row_id: int) -> str:
    """Encode a keyset cursor as an opaque base64 string."""
    return base64.b64encode(
        json.dumps({"id": row_id}).encode()
    ).decode()


def _decode_cursor(cursor: str) -> int:
    """Decode a keyset cursor; raises ValueError if malformed."""
    try:
        payload = json.loads(base64.b64decode(cursor).decode())
        return int(payload["id"])
    except Exception as exc:
        raise ValueError("Invalid cursor") from exc


def create_job(
    run_id: str,
    status: str,
    callback_url: str | None,
    article_count: int,
) -> JobRow:
    """Insert a classification_jobs row and return it."""
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO classification_jobs
                (run_id, status, callback_url, article_count)
            VALUES (:run_id, :status, :callback_url, :article_count)
            RETURNING *
            """,
            {
                "run_id": run_id,
                "status": status,
                "callback_url": callback_url,
                "article_count": article_count,
            },
        ).fetchone()
    return JobRow(row)


def get_job(job_id: int) -> JobRow | None:
    """Return a classification_jobs row by id, or None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM classification_jobs WHERE id = :job_id",
            {"job_id": job_id},
        ).fetchone()
    return JobRow(row) if row else None


def get_job_stats(job_id: int) -> dict[str, int]:
    """Return label counts for a completed job."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT label, COUNT(*) AS cnt
            FROM classifications
            WHERE job_id = :job_id
            GROUP BY label
            """,
            {"job_id": job_id},
        ).fetchall()
    return {row["label"]: row["cnt"] for row in rows}


def list_job_results(
    job_id: int,
    after_id: int,
    limit: int,
) -> tuple[list[ClassificationRow], str | None]:
    """Return a page of classifications for a job.

    Returns (rows, next_cursor). next_cursor is None when no more pages.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM classifications
            WHERE job_id = :job_id AND id > :after_id
            ORDER BY id ASC
            LIMIT :fetch
            """,
            {"job_id": job_id, "after_id": after_id, "fetch": limit + 1},
        ).fetchall()
    if len(rows) > limit:
        next_cursor = _encode_cursor(rows[limit - 1]["id"])
        rows = rows[:limit]
    else:
        next_cursor = None
    return [ClassificationRow(r) for r in rows], next_cursor


def update_job_status(
    job_id: int,
    status: str,
    set_completed_at: bool = True,
) -> None:
    """Update a job's status, optionally stamping completed_at."""
    if set_completed_at:
        sql = """
            UPDATE classification_jobs
            SET status = :status, completed_at = NOW()
            WHERE id = :job_id
        """
    else:
        sql = """
            UPDATE classification_jobs
            SET status = :status
            WHERE id = :job_id
        """
    with get_db() as conn:
        conn.execute(sql, {"status": status, "job_id": job_id})


def find_processing_job(run_id: str) -> JobRow | None:
    """Return the processing job for run_id if one exists."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM classification_jobs
            WHERE run_id = :run_id AND status = 'processing'
            """,
            {"run_id": run_id},
        ).fetchone()
    return JobRow(row) if row else None
