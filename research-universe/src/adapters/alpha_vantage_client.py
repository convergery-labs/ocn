"""Alpha Vantage adapter: symbol search and company overview."""
from __future__ import annotations

import logging

import httpx

import config

logger = logging.getLogger(__name__)

_BASE = "https://www.alphavantage.co/query"


def symbol_search(keyword: str) -> list[dict]:
    """Search for equity symbols matching keyword.

    Returns a list of matches with keys: symbol, name, type, region, currency.
    Filters out non-Equity types (ETFs, mutual funds, indices).
    """
    resp = httpx.get(
        _BASE,
        params={"function": "SYMBOL_SEARCH", "keywords": keyword, "apikey": config.ALPHA_VANTAGE_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    matches = []
    for m in data.get("bestMatches", []):
        if m.get("3. type") != "Equity":
            continue
        matches.append(
            {
                "symbol": m.get("1. symbol", ""),
                "name": m.get("2. name", ""),
                "type": m.get("3. type", ""),
                "region": m.get("4. region", ""),
                "currency": m.get("8. currency", ""),
            }
        )
    return matches


def overview(ticker: str) -> dict | None:
    """Fetch company overview for a ticker.

    Returns the raw OVERVIEW dict, or None if Alpha Vantage returns no data
    (e.g. unknown ticker, rate limit hit).
    """
    resp = httpx.get(
        _BASE,
        params={"function": "OVERVIEW", "symbol": ticker, "apikey": config.ALPHA_VANTAGE_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if not data or "Symbol" not in data:
        logger.debug("No OVERVIEW data for %s", ticker)
        return None
    return data
