"""Repository functions for classification_jobs and classifications."""
from datetime import datetime
from typing import Any

from cursor_utils import decode_cursor, encode_cursor
from db import get_db


class JobRow(dict):
    """Row from classification_jobs."""


class ClassificationRow(dict):
    """Row from classifications."""


def _encode_cursor(row_id: int) -> str:
    """Encode a keyset cursor as an opaque base64 string."""
    return encode_cursor({"id": row_id})


def _decode_cursor(cursor: str) -> int:
    """Decode a keyset cursor; raises ValueError if malformed."""
    return decode_cursor(cursor)["id"]


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


def insert_classification(
    job_id: int,
    article_url: str,
    article_embedding: list[float],
    model_embedding: str,
    model_llm: str,
) -> int:
    """Insert a placeholder classification row and return its id.

    label='Noise' and composite_score=0.0 are placeholders;
    CON-138 will UPDATE these with actual scores and labels.
    """
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO classifications
                (job_id, article_url, label, composite_score,
                 model_embedding, model_llm, article_embedding)
            VALUES
                (:job_id, :article_url, 'Noise', 0.0,
                 :model_embedding, :model_llm, :article_embedding)
            RETURNING id
            """,
            {
                "job_id": job_id,
                "article_url": article_url,
                "model_embedding": model_embedding,
                "model_llm": model_llm,
                "article_embedding": article_embedding,
            },
        ).fetchone()
    return row["id"]


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


def get_classification(
    classification_id: int,
) -> ClassificationRow | None:
    """Return a classifications row by id, or None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM classifications WHERE id = :id",
            {"id": classification_id},
        ).fetchone()
    return ClassificationRow(row) if row else None


def insert_deferred_promotion(
    classification_id: int,
    promote_at: datetime,
) -> None:
    """Insert a deferred_promotions row for a Signal article."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO deferred_promotions
                (classification_id, promote_at)
            VALUES (:classification_id, :promote_at)
            """,
            {
                "classification_id": classification_id,
                "promote_at": promote_at,
            },
        )


def get_pending_promotions() -> list[dict[str, Any]]:
    """Return deferred_promotions due for processing.

    Returns rows where promote_at <= NOW() and promoted_at IS NULL,
    joined with classifications to include article_embedding and cluster_id.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                dp.id            AS promotion_id,
                dp.classification_id,
                dp.promote_at,
                c.article_embedding,
                c.cluster_id,
                c.label          AS original_label
            FROM deferred_promotions dp
            JOIN classifications c ON c.id = dp.classification_id
            WHERE dp.promote_at <= NOW()
              AND dp.promoted_at IS NULL
            ORDER BY dp.promote_at ASC
            """,
        ).fetchall()
    return [dict(r) for r in rows]


def mark_promotion_done(
    promotion_id: int,
    final_label: str,
) -> None:
    """Set promoted_at = NOW() and final_label on a deferred_promotions row."""
    with get_db() as conn:
        conn.execute(
            """
            UPDATE deferred_promotions
            SET promoted_at = NOW(), final_label = :final_label
            WHERE id = :promotion_id
            """,
            {
                "promotion_id": promotion_id,
                "final_label": final_label,
            },
        )


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
