"""Repository layer - japan_progress_habits table.

Japan Signals spec Section 6.2's own stored comparison point for J2
(results against forecast) - see db.py's table comment for the full
design rationale. Refreshed periodically (see japan_company_habits.py's
own module docstring for the equivalent J1 refresh flow), read by
classify_results_against_forecast.
"""
from __future__ import annotations

from typing import Any

from db import get_db


def replace_progress_habits(habits: list[dict[str, Any]]) -> None:
    """Overwrite the entire cache with freshly-computed progress habits,
    one row per (code, period_type) pair. Each dict needs code,
    period_type, company, typical_progress_pct, sample_size, is_trusted.

    One transaction: delete-then-insert, same reasoning as
    japan_company_habits.replace_habits - a partial refresh must never
    leave a mix of old and new data.
    """
    with get_db() as conn:
        conn.execute("DELETE FROM japan_progress_habits")
        if not habits:
            return
        conn.execute_values(
            """
            INSERT INTO japan_progress_habits
                (code, period_type, company, typical_progress_pct, sample_size, is_trusted)
            VALUES %s
            """,
            [
                (
                    h["code"],
                    h["period_type"],
                    h["company"],
                    h["typical_progress_pct"],
                    h["sample_size"],
                    h["is_trusted"],
                )
                for h in habits
            ],
        )


def get_all_progress_habits() -> dict[tuple[str, str], dict[str, Any]]:
    """Return {(code, period_type): habit_dict} for every stored progress
    habit - classify_results_against_forecast loads this ONCE per batch,
    same "load whole cache, look up per item" shape as japan_company_
    habits.get_all_habits().
    """
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM japan_progress_habits").fetchall()
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        result[(row["code"], row["period_type"])] = {
            "typical_progress_pct": float(row["typical_progress_pct"]) if row["typical_progress_pct"] is not None else None,
            "sample_size": row["sample_size"],
            "is_trusted": row["is_trusted"],
        }
    return result
