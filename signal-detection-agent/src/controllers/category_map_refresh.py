"""Refresh job for Stage C's shared company cache (feeds both Layer 1's
direct name match and Layer 3's category->ticker expansion - see db.py's
table comment for why these share one cache).

Runs on its own schedule, independent of Stage C's own runs - Stage C only
ever reads the cache, never calls research-universe directly, keeping both
layers a free, deterministic lookup.
"""
from __future__ import annotations

import logging
import re

from adapters.research_universe_client import fetch_us_listed_companies
from models.geopolitical_signal_companies import replace_companies
from pipeline.categories import ALLOWED_CATEGORIES

logger = logging.getLogger(__name__)

# Confirmed live: research-universe's GET /companies returns category names
# with a leading ordinal prefix ("01. Raw Materials & Critical Minerals"),
# but ALLOWED_CATEGORIES (pipeline/categories.py) holds bare names with no
# prefix - that file is shared with the news classifier's LLM-output
# validation, which never touches research-universe's API directly, so the
# mismatch was never previously exposed. Stripped here, at the one place
# that actually compares the two, rather than changing ALLOWED_CATEGORIES
# itself (broader blast radius - the Stage C prompt and existing LLM
# validation both already rely on the bare, unprefixed form).
_ORDINAL_PREFIX_RE = re.compile(r"^\d+\.\s*")


def _strip_ordinal_prefix(category: str) -> str:
    return _ORDINAL_PREFIX_RE.sub("", category).strip()


def _normalize_companies(raw_companies: list[dict]) -> list[dict]:
    """Filter to companies with a real ticker (not "Private"/missing), and
    normalize each company's categories to only names in ALLOWED_CATEGORIES
    (ordinal prefix stripped; anything unrecognized after that is dropped
    with a warning rather than silently stored as-is - either
    research-universe's taxonomy has drifted from this service's copy
    (pipeline/categories.py) or this is genuinely new data that needs that
    file updated first).
    """
    result: list[dict] = []
    unknown_categories: set[str] = set()
    for company in raw_companies:
        ticker = company.get("ticker")
        if not ticker or ticker == "Private":
            continue
        categories: list[str] = []
        for raw_category in company.get("categories") or []:
            category = _strip_ordinal_prefix(raw_category)
            if category in ALLOWED_CATEGORIES:
                categories.append(category)
            else:
                unknown_categories.add(raw_category)
        result.append({
            "ticker": ticker,
            "company_name": company.get("company_name") or "",
            "categories": categories,
        })
    if unknown_categories:
        logger.warning(
            "[CATEGORY_MAP_REFRESH] research-universe returned %d categor"
            "y/ies not in ALLOWED_CATEGORIES (after prefix-stripping),"
            " skipped: %s",
            len(unknown_categories), sorted(unknown_categories),
        )
    return result


async def refresh_category_ticker_map() -> dict[str, int]:
    """Fetch the current US-listed universe from research-universe,
    normalize, overwrite the shared company cache. Returns per-category
    ticker counts for logging/verification.
    """
    raw_companies = await fetch_us_listed_companies()
    companies = _normalize_companies(raw_companies)
    replace_companies(companies)

    counts: dict[str, int] = {c: 0 for c in ALLOWED_CATEGORIES}
    for company in companies:
        for category in company["categories"]:
            counts[category] += 1
    logger.info(
        "[CATEGORY_MAP_REFRESH] companies=%d categories=%d total_ticker_slots=%d",
        len(companies), len(counts), sum(counts.values()),
    )
    return counts
