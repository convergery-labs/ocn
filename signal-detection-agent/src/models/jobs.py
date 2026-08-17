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
                pre_verification_score, verification_qa,
                published
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                article.get("published"),
            ),
        )


def insert_filing_classification(job_id: int, filing: dict[str, Any], result: dict[str, Any]) -> None:
    """Upsert one agent_classifications row for an SEC filing (source_type='sec_filing').

    category is left NULL - not computed at this stage for filings.
    materiality matches the base-pass news schema (high/medium/low/none).
    """
    entity_names_normalized = [
        e["name"].lower() for e in (result.get("entities") or []) if e.get("name")
    ]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agent_classifications (
                job_id, source_type, source_id, url, title,
                signal_detection, signal_score, signal_reason, materiality,
                entities_json, entity_names_normalized,
                form_type, item_codes, filing_filed_at
            ) VALUES (%s, 'sec_filing', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                job_id,
                filing.get("accession_number"),
                result.get("primary_doc_url", ""),
                f"{filing.get('ticker', '')} {filing.get('form_type', '')} filing",
                result["signal_detection"],
                float(result["signal_score"]),
                result.get("signal_reason"),
                result.get("materiality"),
                json.dumps(result.get("entities") or [], ensure_ascii=False),
                entity_names_normalized,
                result.get("form_type"),
                result.get("item_codes") or [],
                result.get("filed_at") or None,
            ),
        )


def insert_geopolitical_classification(job_id: int, article: dict[str, Any], result: dict[str, Any]) -> None:
    """Upsert one agent_classifications row for a geopolitical article (source_type='geopolitical').

    category and materiality are left NULL - the geopolitical prompt does not
    assign either (deferred to a later stage, see prompts/geopolitical_classifier_v1.txt).
    concreteness/economic_scale are the two factor sub-scores unique to this domain.
    """
    entity_names_normalized = [
        e["name"].lower() for e in (result.get("entities") or []) if e.get("name")
    ]
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO agent_classifications (
                job_id, source_type, source_id, url, title,
                signal_detection, signal_score, signal_reason,
                concreteness, economic_scale,
                entities_json, entity_names_normalized, published
            ) VALUES (%s, 'geopolitical', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                result.get("concreteness"),
                result.get("economic_scale"),
                json.dumps(result.get("entities") or [], ensure_ascii=False),
                entity_names_normalized,
                article.get("published"),
            ),
        )


def get_existing_filing_source_ids(source_ids: list[str]) -> set[str]:
    """Return the subset of source_ids (accession_numbers) already classified
    as source_type='sec_filing'. One batched query, not one per filing - used
    to diff a day's fetched filings against what's already in the table before
    calling the classifier, so unchanged filings are never reclassified.
    """
    if not source_ids:
        return set()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT source_id FROM agent_classifications
            WHERE source_type = 'sec_filing' AND source_id = ANY(%s)
            """,
            (source_ids,),
        ).fetchall()
    return {r["source_id"] for r in rows}


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


def list_jobs(
    limit: int = 20,
    cursor: str | None = None,
    status: str | None = "completed",
    domain: str | None = None,
) -> dict[str, Any]:
    """Return cursor-paginated agent_jobs, newest-first. Defaults to completed only.

    domain filters to agent_jobs.domain - callers that poll for "the latest
    job" across multiple domains (news, sec_filing, ...) must pass this,
    otherwise "most recent completed job" can return a job from a different
    domain than the one they actually wanted (e.g. a same-day SEC filing job
    completing after the news job would otherwise silently win).
    """
    params: list[Any] = []
    conditions: list[str] = []
    if status:
        conditions.append("status = %s")
        params.append(status)
    if domain:
        conditions.append("domain = %s")
        params.append(domain)
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
    limit: int = 100,
    cursor: str | None = None,
    signal_detection: str | None = None,
    source_type: str | None = None,
) -> dict[str, Any]:
    """Return cursor-paginated agent_classifications across all jobs, newest first."""
    params: list[Any] = []
    conditions = []
    if signal_detection:
        conditions.append("signal_detection = %s")
        params.append(signal_detection)
    if source_type:
        conditions.append("source_type = %s")
        params.append(source_type)
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
    job_id: int,
    limit: int = 100,
    cursor: str | None = None,
    signal_detection: str | None = None,
    source_type: str | None = None,
) -> dict[str, Any]:
    """Return cursor-paginated agent_classifications for a job."""
    params: list[Any] = [job_id]
    extra_conditions = ""
    if signal_detection:
        extra_conditions += " AND signal_detection = %s"
        params.append(signal_detection)
    if source_type:
        extra_conditions += " AND source_type = %s"
        params.append(source_type)
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
