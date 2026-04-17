"""DB query functions for pipeline run records."""
import base64
import json
from datetime import date, datetime
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
    focus: Optional[str]
    article_count: Optional[int]
    summary: Optional[str]
    callback_url: Optional[str]


def _encode_run_cursor(started_at: datetime, run_id: int) -> str:
    """Encode a run keyset position as an opaque cursor string."""
    payload = json.dumps(
        {"ts": started_at.isoformat(), "id": run_id}
    )
    return base64.b64encode(payload.encode()).decode()


def _decode_run_cursor(cursor: str) -> tuple[datetime, int]:
    """Decode a run cursor; raises ValueError if malformed."""
    try:
        payload = json.loads(base64.b64decode(cursor).decode())
        return datetime.fromisoformat(payload["ts"]), int(payload["id"])
    except Exception as exc:
        raise ValueError("Invalid cursor") from exc


def create_run(
    name: str,
    domain: str,
    days_back: int,
    max_articles: Optional[int],
    focus: Optional[str],
    callback_url: Optional[str] = None,
) -> int:
    """Insert a new run record and return its id."""
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO runs
                (name, domain, days_back, max_articles, focus,
                 status, callback_url)
            VALUES
                (:name, :domain, :days_back, :max_articles,
                 :focus, 'running', :callback_url)
            RETURNING id
            """,
            {
                "name": name,
                "domain": domain,
                "days_back": days_back,
                "max_articles": max_articles,
                "focus": focus,
                "callback_url": callback_url,
            },
        )
        return cur.fetchone()["id"]


def complete_run(run_id: int, article_count: int) -> None:
    """Mark a run as completed with its article count."""
    with get_db() as conn:
        conn.execute(
            """
            UPDATE runs
            SET status        = 'completed',
                completed_at  = CURRENT_TIMESTAMP,
                article_count = :article_count
            WHERE id = :id
            """,
            {"id": run_id, "article_count": article_count},
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


def list_runs(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> tuple[list[RunRow], Optional[str]]:
    """Return filtered, paginated runs ordered newest-first.

    Returns a (rows, next_cursor) tuple. next_cursor is None when
    there are no further pages.
    """
    params: dict = {}
    clauses: list[str] = []

    if domain is not None:
        clauses.append("domain = :domain")
        params["domain"] = domain

    if status is not None:
        clauses.append("status = :status")
        params["status"] = status

    if from_date is not None:
        clauses.append("started_at >= :from_date")
        params["from_date"] = from_date

    if to_date is not None:
        clauses.append("started_at <= :to_date")
        params["to_date"] = to_date

    if cursor is not None:
        cursor_ts, cursor_id = _decode_run_cursor(cursor)
        clauses.append(
            "(started_at < :cursor_ts"
            " OR (started_at = :cursor_ts AND id < :cursor_id))"
        )
        params["cursor_ts"] = cursor_ts
        params["cursor_id"] = cursor_id

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params["limit"] = limit + 1

    with get_db() as conn:
        cur = conn.execute(
            f"""
            SELECT * FROM runs
            {where}
            ORDER BY started_at DESC, id DESC
            LIMIT :limit
            """,
            params,
        )
        rows = [dict(r) for r in cur.fetchall()]

    next_cursor: Optional[str] = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_run_cursor(last["started_at"], last["id"])

    return rows, next_cursor  # type: ignore[return-value]


def get_running_run_for_domain(domain: str) -> Optional[int]:
    """Return the id of any currently running run for domain, or None."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT id FROM runs"
            " WHERE domain = :domain AND status = 'running' LIMIT 1",
            {"domain": domain},
        )
        row = cur.fetchone()
        return row["id"] if row else None


def get_run(run_id: int) -> Optional[RunRow]:
    """Return a single run by id, or None if not found."""
    with get_db() as conn:
        cur = conn.execute(
            "SELECT * FROM runs WHERE id = :id",
            {"id": run_id},
        )
        row = cur.fetchone()
        return dict(row) if row else None  # type: ignore[return-value]
