"""Repository layer - japan_company_habits table.

Japan Signals spec Section 4.1's own stored pattern per company - see
db.py's table comment for the full design rationale (explicit user
instruction 2026-09-28: compute these four numbers once from stored
history, save them per company, then compare a new revision against that
company's own numbers instead of recomputing/using a fixed threshold).
Refreshed periodically by refresh-japan-habits (see __main__.py), read
(never written outside that refresh) by classify_forecast_revision.
"""
from __future__ import annotations

from typing import Any

from db import get_db


def replace_habits(habits: list[dict[str, Any]]) -> None:
    """Overwrite the entire cache with freshly-computed habits, one row
    per company. Each dict needs code, company, revisions_per_year,
    typical_size_pct, typical_size_mad_pct, typical_direction,
    typical_months (list[int], up to 3), sample_size, is_trusted,
    computed_from_years.

    typical_size_mad_pct is None for a margin-based company's row (see
    compute_margin_revision_habit's own docstring - that company's
    typical_gap_pts lives in the typical_size_pct slot instead, with no
    MAD computed for it - classify_margin_forecast_revision's own
    2-rule chain doesn't use a MAD-based bar) - stored as SQL NULL via
    .get(), not a required key, same "not every habit shape needs every
    column" convention typical_month_1-3 already follow for a company
    with fewer than 3 distinct months.

    One transaction: delete-then-insert, same reasoning as
    geopolitical_signal_companies.replace_companies - a partial refresh
    (e.g. failing halfway through 20 companies) must never leave a mix of
    an old habit for one company and a new one for another, since
    classify_forecast_revision has no way to tell those apart once stored.
    """
    with get_db() as conn:
        conn.execute("DELETE FROM japan_company_habits")
        if not habits:
            return
        conn.execute_values(
            """
            INSERT INTO japan_company_habits
                (code, company, revisions_per_year, typical_size_pct,
                 typical_size_mad_pct, typical_direction, typical_month_1,
                 typical_month_2, typical_month_3, sample_size, is_trusted,
                 computed_from_years)
            VALUES %s
            """,
            [
                (
                    h["code"],
                    h["company"],
                    h["revisions_per_year"],
                    h["typical_size_pct"],
                    h.get("typical_size_mad_pct"),
                    h["typical_direction"],
                    h["typical_months"][0] if len(h["typical_months"]) > 0 else None,
                    h["typical_months"][1] if len(h["typical_months"]) > 1 else None,
                    h["typical_months"][2] if len(h["typical_months"]) > 2 else None,
                    h["sample_size"],
                    h["is_trusted"],
                    h["computed_from_years"],
                )
                for h in habits
            ],
        )


def get_all_habits() -> dict[str, dict[str, Any]]:
    """Return {code: habit_dict} for every stored company habit -
    classify_forecast_revision loads this ONCE per batch (not once per
    article), same "load whole cache into memory, look up per item" shape
    Stage C's own Layer 1 uses for geopolitical_signal_companies.

    typical_months is reassembled into a list (dropping any None slots),
    the mirror image of replace_habits's own column-per-slot storage -
    callers get back the same shape compute_forecast_habit produces, not
    the storage-level column layout.
    """
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM japan_company_habits").fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        months = [
            row[f"typical_month_{i}"] for i in (1, 2, 3) if row[f"typical_month_{i}"] is not None
        ]
        result[row["code"]] = {
            "revisions_per_year": float(row["revisions_per_year"]) if row["revisions_per_year"] is not None else None,
            "typical_size_pct": float(row["typical_size_pct"]) if row["typical_size_pct"] is not None else None,
            "typical_size_mad_pct": float(row["typical_size_mad_pct"]) if row["typical_size_mad_pct"] is not None else None,
            "typical_direction": row["typical_direction"],
            "typical_months": months,
            "sample_size": row["sample_size"],
            "is_trusted": row["is_trusted"],
        }
    return result


def get_habits_refreshed_at() -> Any | None:
    """Return the most recent refreshed_at, or None if never populated -
    same staleness-check role as geopolitical_signal_companies' own
    get_companies_refreshed_at.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT max(refreshed_at) AS refreshed_at FROM japan_company_habits",
        ).fetchone()
    return row["refreshed_at"] if row else None
