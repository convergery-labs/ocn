"""Repository layer - japan_company_reference table.

J5 (capacity commitment) and J6 (ownership/capital policy) denominators -
see db.py's table comment and japan_signal_classifier.classify_capacity_
and_ownership's own docstring for the full design rationale. Unlike
japan_company_habits/japan_progress_habits, this is a plain cache of the
latest value news-retrieval's irbank_company_reference source reported,
not a habit computed from stored history. Refreshed periodically by
refresh-japan-habits (see __main__.py, same refresh job that already
handles the other two Japan habit tables), read (never written outside
that refresh) by classify_capacity_and_ownership.
"""
from __future__ import annotations

from typing import Any

from db import get_db


def replace_company_reference(rows: list[dict[str, Any]]) -> None:
    """Overwrite the entire cache with freshly-fetched reference facts,
    one row per company. Each dict needs code, company,
    total_assets_jpy_millions, shares_outstanding, fiscal_period.

    One transaction: delete-then-insert, same reasoning as
    japan_company_habits.replace_habits - a partial refresh must never
    leave a mix of an old figure for one company and a new one for
    another.
    """
    with get_db() as conn:
        conn.execute("DELETE FROM japan_company_reference")
        if not rows:
            return
        conn.execute_values(
            """
            INSERT INTO japan_company_reference
                (code, company, total_assets_jpy_millions, shares_outstanding, fiscal_period)
            VALUES %s
            """,
            [
                (
                    r["code"],
                    r["company"],
                    r.get("total_assets_jpy_millions"),
                    r.get("shares_outstanding"),
                    r.get("fiscal_period"),
                )
                for r in rows
            ],
        )


def get_all_company_reference() -> dict[str, dict[str, Any]]:
    """Return {code: reference_dict} for every stored company reference
    row - classify_capacity_and_ownership loads this ONCE per batch (not
    once per article), same "load whole cache into memory, look up per
    item" shape japan_company_habits.get_all_habits already uses.
    """
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM japan_company_reference").fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        result[row["code"]] = {
            "total_assets_jpy_millions": float(row["total_assets_jpy_millions"]) if row["total_assets_jpy_millions"] is not None else None,
            "shares_outstanding": row["shares_outstanding"],
            "fiscal_period": row["fiscal_period"],
        }
    return result


def get_company_reference_refreshed_at() -> Any | None:
    """Return the most recent refreshed_at, or None if never populated -
    same staleness-check role as japan_company_habits.get_habits_refreshed_at.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT max(refreshed_at) AS refreshed_at FROM japan_company_reference",
        ).fetchone()
    return row["refreshed_at"] if row else None
