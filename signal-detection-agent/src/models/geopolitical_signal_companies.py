"""Repository layer - geopolitical_signal_companies table.

Stage C's shared company cache, refreshed periodically from
research-universe (see controllers/category_map_refresh.py). Serves both
Layer 1 (direct name-in-headline match: needs company_name+ticker) and
Layer 3 (category->ticker expansion: needs categories+ticker) from one
table, one refresh - see db.py's table comment for why this isn't two
separate caches. Read (never written) by Stage C itself.
"""
from __future__ import annotations

from typing import Any

from db import get_db


def replace_companies(companies: list[dict[str, Any]]) -> None:
    """Overwrite the entire cache with a freshly-fetched company list.
    Each dict needs ticker, company_name, categories (list[str], already
    normalized - no ordinal prefixes, only names in ALLOWED_CATEGORIES).

    One transaction: delete-then-insert, not a per-row upsert, so a
    partial refresh never leaves a mix of old and new data. Insert is a
    single batched execute_values call rather than one INSERT per row -
    706+ round trips for a routine cache refresh has no upside.
    """
    with get_db() as conn:
        conn.execute("DELETE FROM geopolitical_signal_companies")
        if not companies:
            return
        conn.execute_values(
            """
            INSERT INTO geopolitical_signal_companies (ticker, company_name, categories)
            VALUES %s
            """,
            [(c["ticker"], c["company_name"], c["categories"]) for c in companies],
        )


def get_companies_for_name_matching() -> list[dict[str, Any]]:
    """Return every cached company (ticker, company_name), longest name
    first - Layer 1 loads this once per Stage C run (not once per
    article), then matches in memory; longest-first ordering means a
    specific, longer name is checked before a shorter name that might
    accidentally be a substring of it.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT ticker, company_name FROM geopolitical_signal_companies
            ORDER BY length(company_name) DESC
            """,
        ).fetchall()
    return [dict(r) for r in rows]


# Maximum tickers returned per article. A category is an unweighted
# membership list, so expansion size is a property of the category, not of
# the story: confirmed live in staging that one chosen category yields 8
# tickers (Defense, Aerospace & Sovereign AI) or 50 (Energy & Grid
# Infrastructure) purely by how many companies sit in it, and two chosen
# categories yielded 58. A 58-ticker list is not a more useful answer than
# an 8-ticker one - past roughly this size the field stops naming the
# companies a reader should look at and just restates the category's
# membership, which the category name already said.
#
# NOT a relevance ranking - the cache holds only ticker/company_name/
# categories (no market cap, index weight or revenue exposure), so there is
# nothing here to rank BY. Ranking would need research-universe to supply a
# weight through controllers/category_map_refresh.py first. Until then this
# is an honest truncation: deterministic (ticker order), and the caller is
# told the list was cut rather than being handed a silently partial list
# that looks complete.
_MAX_TICKERS_PER_ARTICLE = 25


def get_tickers_for_categories(
    categories: list[str], *, limit: int = _MAX_TICKERS_PER_ARTICLE,
) -> tuple[list[dict[str, Any]], int]:
    """Return (tickers, total_matched) for exactly the given category names
    - Layer 3's expansion step, reading only the categories Layer 2 (+
    overrides) actually chose rather than the full 19-category table.

    One entry per ticker (not per ticker-category pair) - matched_categories
    is a list so a ticker exposed via multiple chosen categories (a real,
    common case: e.g. a Canada-tariff headline spanning Semiconductor
    Manufacturing + Cloud & Compute Platforms) appears once with both
    categories named, rather than as duplicate rows.

    ``tickers`` is capped at ``limit`` (see _MAX_TICKERS_PER_ARTICLE for
    why, and for why this is truncation rather than a ranking).
    ``total_matched`` is the uncapped count, so a caller can show "25 of
    58" rather than presenting a truncated list as the whole answer.
    Ordering is by ticker - arbitrary but deterministic, so the same
    article re-tagged keeps the same list instead of reshuffling on each
    run.
    """
    if not categories:
        return [], 0
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT ticker, company_name, categories FROM geopolitical_signal_companies
            WHERE categories && %s
            ORDER BY ticker
            """,
            (categories,),
        ).fetchall()
    category_set = set(categories)
    result: list[dict[str, Any]] = []
    for row in rows:
        matched = [c for c in row["categories"] if c in category_set]
        if matched:
            result.append({
                "ticker": row["ticker"],
                "company_name": row["company_name"],
                "matched_categories": matched,
            })
    return result[:limit], len(result)


def get_companies_refreshed_at() -> Any | None:
    """Return the most recent refreshed_at, or None if the cache has never
    been populated - lets a caller/health-check answer "how stale is this
    data" without reading the whole table.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT max(refreshed_at) AS refreshed_at FROM geopolitical_signal_companies",
        ).fetchone()
    return row["refreshed_at"] if row else None
