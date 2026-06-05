"""Repository layer - agent_jobs and agent_classifications tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from cursor_utils import decode_cursor, encode_cursor
from db import get_db


def create_job(domain: str, news_run_id: int | None = None) -> int:
    """Insert a new agent_jobs row with status=pending; return its id."""
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO agent_jobs (domain, news_run_id, status)
            VALUES (%s, %s, 'pending')
            RETURNING id
            """,
            (domain, news_run_id),
        ).fetchone()
    return int(row["id"])


def update_job_status(
    job_id: int,
    status: str,
    *,
    article_count: int | None = None,
    set_completed_at: bool = False,
) -> None:
    """Update job status and optionally article_count / completed_at."""
    if article_count is not None and set_completed_at:
        with get_db() as conn:
            conn.execute(
                """
                UPDATE agent_jobs
                SET status = %s, article_count = %s,
                    completed_at = NOW()
                WHERE id = %s
                """,
                (status, article_count, job_id),
            )
    elif article_count is not None:
        with get_db() as conn:
            conn.execute(
                "UPDATE agent_jobs SET status = %s, article_count = %s WHERE id = %s",
                (status, article_count, job_id),
            )
    elif set_completed_at:
        with get_db() as conn:
            conn.execute(
                "UPDATE agent_jobs SET status = %s, completed_at = NOW() WHERE id = %s",
                (status, job_id),
            )
    else:
        with get_db() as conn:
            conn.execute(
                "UPDATE agent_jobs SET status = %s WHERE id = %s",
                (status, job_id),
            )


def insert_classification(job_id: int, article: dict[str, Any], result: dict[str, Any]) -> None:
    """Upsert one agent_classifications row."""
    entity_names_normalized = [
        e["name"].lower() for e in (result.get("entities") or []) if e.get("name")
    ]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agent_classifications (
                job_id, article_id, url, title,
                signal_detection, signal_score, signal_reason,
                materiality, category, entities_json,
                base_signal_detection, base_signal_score,
                novelty, novelty_basis, confidence, confidence_basis,
                refinement_reason, entity_names_normalized,
                pre_verification_score, verification_qa
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                job_id,
                article.get("id"),
                article.get("url"),
                article.get("title"),
                result["signal_detection"],
                float(result["signal_score"]),
                result.get("signal_reason"),
                result["materiality"],
                result["category"],
                json.dumps(result.get("entities") or [], ensure_ascii=False),
                result.get("base_signal_detection"),
                result.get("base_signal_score"),
                result.get("novelty"),
                result.get("novelty_basis"),
                result.get("confidence"),
                result.get("confidence_basis"),
                result.get("refinement_reason"),
                entity_names_normalized,
                result.get("pre_verification_score"),
                json.dumps(result.get("verification_qa") or [], ensure_ascii=False),
            ),
        )


def get_recent_entity_classifications(
    entity_names: list[str],
    *,
    days: int = 90,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """Return recent rows that mention any of the given entity names.

    Includes signal/weak_signal rows (for novelty and downgrade decisions) and
    borderline noise rows with signal_score >= 0.28 (as escalation context).
    Stage 2 uses the signal_detection field to distinguish the two.
    """
    if not entity_names:
        return []
    normalized_names = [name.lower() for name in entity_names]
    placeholders = ", ".join(["%s"] * len(normalized_names))
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT signal_detection, signal_score, signal_reason, category,
                   entities_json, title, url, stored_at
            FROM agent_classifications
            WHERE stored_at >= NOW() - INTERVAL '{days} days'
              AND (
                signal_detection IN ('signal', 'weak_signal')
                OR (signal_detection = 'noise' AND signal_score >= 0.28)
              )
              AND entity_names_normalized && ARRAY[{placeholders}]::TEXT[]
            ORDER BY stored_at DESC
            LIMIT %s
            """,
            [*normalized_names, limit],
        ).fetchall()
    results = []
    for r in rows:
        rec = dict(r)
        rec["entities"] = json.loads(rec.pop("entities_json", "[]") or "[]")
        if rec.get("signal_score") is not None:
            rec["signal_score"] = float(rec["signal_score"])
        if rec.get("stored_at") is not None:
            rec["stored_at"] = rec["stored_at"].isoformat()
        results.append(rec)
    return results


def get_completed_job_for_run(news_run_id: int) -> dict[str, Any] | None:
    """Return the most recent completed job for a given news_run_id, or None."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM agent_jobs
            WHERE news_run_id = %s AND status = 'completed'
            ORDER BY id DESC LIMIT 1
            """,
            (news_run_id,),
        ).fetchone()
    return dict(row) if row else None


def get_job(job_id: int) -> dict[str, Any] | None:
    """Return a single agent_jobs row, or None if not found."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM agent_jobs WHERE id = %s", (job_id,)
        ).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 20, cursor: str | None = None, status: str | None = "completed") -> dict[str, Any]:
    """Return cursor-paginated agent_jobs, newest-first. Defaults to completed only."""
    params: list[Any] = []
    conditions: list[str] = []
    if status:
        conditions.append("status = %s")
        params.append(status)
    if cursor:
        after_id = decode_cursor(cursor)
        conditions.append("id < %s")
        params.append(after_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit + 1)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM agent_jobs {where} ORDER BY id DESC LIMIT %s",
            params,
        ).fetchall()
    jobs = [dict(r) for r in rows]
    next_cursor = None
    if len(jobs) > limit:
        jobs = jobs[:limit]
        next_cursor = encode_cursor(jobs[-1]["id"])
    return {"jobs": jobs, "next_cursor": next_cursor}


def list_all_results(
    limit: int = 100, cursor: str | None = None, signal_detection: str | None = None
) -> dict[str, Any]:
    """Return cursor-paginated agent_classifications across all jobs, newest first."""
    params: list[Any] = []
    conditions = []
    if signal_detection:
        conditions.append("signal_detection = %s")
        params.append(signal_detection)
    if cursor:
        after_id = decode_cursor(cursor)
        conditions.append("id < %s")
        params.append(after_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit + 1)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM agent_classifications
            {where}
            ORDER BY id DESC LIMIT %s
            """,
            params,
        ).fetchall()
    results = []
    for r in rows:
        rec = dict(r)
        rec["entities"] = json.loads(rec.pop("entities_json", "[]") or "[]")
        results.append(rec)
    next_cursor = None
    if len(results) > limit:
        results = results[:limit]
        next_cursor = encode_cursor(results[-1]["id"])
    return {"results": results, "next_cursor": next_cursor}


def list_results(
    job_id: int, limit: int = 100, cursor: str | None = None, signal_detection: str | None = None
) -> dict[str, Any]:
    """Return cursor-paginated agent_classifications for a job."""
    params: list[Any] = [job_id]
    extra_conditions = ""
    if signal_detection:
        extra_conditions += " AND signal_detection = %s"
        params.append(signal_detection)
    if cursor:
        after_id = decode_cursor(cursor)
        extra_conditions += " AND id > %s"
        params.append(after_id)
    params.append(limit + 1)
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM agent_classifications
            WHERE job_id = %s {extra_conditions}
            ORDER BY id ASC LIMIT %s
            """,
            params,
        ).fetchall()
    results = []
    for r in rows:
        rec = dict(r)
        rec["entities"] = json.loads(rec.pop("entities_json", "[]") or "[]")
        results.append(rec)
    next_cursor = None
    if len(results) > limit:
        results = results[:limit]
        next_cursor = encode_cursor(results[-1]["id"])
    return {"results": results, "next_cursor": next_cursor}
