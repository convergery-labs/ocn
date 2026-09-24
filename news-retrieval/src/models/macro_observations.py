"""DB query functions for macro_observations records (macro_signal domain -
FRED + Treasury Fiscal Data raw observations). Not article-shaped, so this
does not reuse models/articles.py's shape, but does reuse the same cursor
pagination helpers."""
import json
from datetime import date
from typing import Any, Optional

from cursor_utils import decode_cursor, encode_cursor
from db import get_db


def _encode_macro_cursor(row_id: int) -> str:
    return encode_cursor({"id": row_id})


def _decode_macro_cursor(cursor: str) -> int:
    return decode_cursor(cursor)["id"]


def insert_macro_observations(observations: list[dict[str, Any]]) -> int:
    """Bulk upsert. ON CONFLICT (series_id, observation_date, vintage)
    DO UPDATE - a never-revised series legitimately gets refetched with
    the same key every run (update-in-place is correct there, not an
    error); an ALFRED first-print row's vintage is fixed once printed, so
    re-fetching it should also just be idempotent, not duplicate.
    Returns the number of rows in the input batch (all upserted)."""
    if not observations:
        return 0
    with get_db() as conn:
        for obs in observations:
            conn.execute(
                """
                INSERT INTO macro_observations
                    (series_id, observation_date, value, knowledge_time,
                     knowledge_time_confidence, vintage, source, raw_payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (series_id, observation_date, COALESCE(vintage, '0001-01-01'::date))
                DO UPDATE SET
                    value = EXCLUDED.value,
                    knowledge_time = EXCLUDED.knowledge_time,
                    knowledge_time_confidence = EXCLUDED.knowledge_time_confidence,
                    source = EXCLUDED.source,
                    raw_payload = EXCLUDED.raw_payload,
                    fetched_at = NOW()
                """,
                (
                    obs["series_id"],
                    obs["observation_date"],
                    obs["value"],
                    obs["knowledge_time"],
                    obs["knowledge_time_confidence"],
                    obs.get("vintage"),
                    obs["source"],
                    json.dumps(obs.get("raw_payload"), default=str),
                ),
            )
    return len(observations)


def get_macro_observations(
    series_ids: Optional[list[str]] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 500,
    cursor: Optional[str] = None,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Cursor-paginated read, ordered (series_id, observation_date), for
    the /macro/observations endpoint."""
    clauses = []
    params: list[Any] = []

    if series_ids:
        clauses.append("series_id = ANY(%s)")
        params.append(series_ids)
    if from_date is not None:
        clauses.append("observation_date >= %s")
        params.append(from_date)
    if to_date is not None:
        clauses.append("observation_date <= %s")
        params.append(to_date)
    if cursor:
        last_id = _decode_macro_cursor(cursor)
        clauses.append("id > %s")
        params.append(last_id)

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit + 1)

    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT id, series_id, observation_date, value, knowledge_time,
                   knowledge_time_confidence, vintage, source, fetched_at
            FROM macro_observations
            {where_sql}
            ORDER BY id
            LIMIT %s
            """,
            tuple(params),
        ).fetchall()

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_macro_cursor(rows[-1]["id"])

    return [dict(r) for r in rows], next_cursor


def get_latest_macro_observation(series_id: str) -> Optional[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id, series_id, observation_date, value, knowledge_time,
                   knowledge_time_confidence, vintage, source, fetched_at
            FROM macro_observations
            WHERE series_id = %s
            ORDER BY observation_date DESC
            LIMIT 1
            """,
            (series_id,),
        ).fetchone()
    return dict(row) if row else None
