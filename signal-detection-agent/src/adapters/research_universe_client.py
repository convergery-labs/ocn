"""HTTP client for research-universe's GET /companies endpoint - the source
of truth for Stage C's category->ticker lookup (Layer 3).

Single unpaginated call: research-universe's /companies route uses plain
limit/offset (not cursor pagination), default limit 5000, max 10000 - the
real universe is ~1,003 companies, so limit=10000 in one call gets
everything, same approach news-retrieval's _fetch_universe_tickers already
uses against this same endpoint.
"""
from __future__ import annotations

from typing import Any

import httpx

import config


class ResearchUniverseError(Exception):
    pass


async def fetch_us_listed_companies() -> list[dict[str, Any]]:
    """Return every US-listed, has-ticker company from research-universe,
    each with company_name, ticker, and categories (a list of taxonomy
    display-name strings - a company can carry more than one).

    Auth is optional server-side (GET /companies uses get_optional_user),
    but the API key is still sent when configured, same as news-retrieval's
    own call to this endpoint.
    """
    headers = {}
    if config.RESEARCH_UNIVERSE_API_KEY:
        headers["Authorization"] = f"Bearer {config.RESEARCH_UNIVERSE_API_KEY}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{config.RESEARCH_UNIVERSE_URL}/companies",
                params={"country": "United States", "has_ticker": "true", "limit": 10000},
                headers=headers,
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ResearchUniverseError(f"Failed to fetch companies: {exc}") from exc
    return resp.json()
