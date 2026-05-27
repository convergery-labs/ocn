"""Thin web search client for entity context lookup."""
from __future__ import annotations

import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ddgs import DDGS

# DuckDuckGo rate-limits aggressively on burst traffic.
# This delay is applied between consecutive DuckDuckGo queries to avoid 202/timeout errors.
_DDGS_INTER_QUERY_DELAY = 1.5  # seconds


def search_entity_context(
    query: str,
    *,
    provider: str = "duckduckgo",
    api_key: str | None = None,
    timeout: int = 5,
    rate_delay: bool = False,
) -> list[dict]:
    """Return [{title, snippet, url}] dicts. Returns [] on any failure.

    Set rate_delay=True when making back-to-back DuckDuckGo calls (e.g. multiple
    entity queries per article) to avoid hitting DuckDuckGo rate limits.
    """
    try:
        if provider == "tavily":
            return _search_tavily(query, api_key=api_key, timeout=timeout)
        if provider == "brave":
            return _search_brave(query, api_key=api_key, timeout=timeout)
        if rate_delay:
            time.sleep(_DDGS_INTER_QUERY_DELAY)
        return _search_duckduckgo(query, timeout=timeout)
    except Exception:
        return []


def _search_duckduckgo(query: str, *, timeout: int) -> list[dict]:
    results = []
    with DDGS(timeout=timeout) as ddgs:
        for r in ddgs.news(query, max_results=5):
            results.append({
                "title": r.get("title", ""),
                "snippet": r.get("body", "")[:300],
                "url": r.get("url", ""),
            })
    return results


def _search_tavily(query: str, *, api_key: str | None, timeout: int) -> list[dict]:
    if not api_key:
        return []
    payload = json.dumps({"api_key": api_key, "query": query, "max_results": 5}).encode()
    req = Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    return [
        {
            "title": r.get("title", ""),
            "snippet": r.get("content", "")[:300],
            "url": r.get("url", ""),
        }
        for r in data.get("results", [])
    ]


def _search_brave(query: str, *, api_key: str | None, timeout: int) -> list[dict]:
    if not api_key:
        return []
    params = urlencode({"q": query, "count": "5"})
    req = Request(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
    )
    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    return [
        {
            "title": r.get("title", ""),
            "snippet": r.get("description", "")[:300],
            "url": r.get("url", ""),
        }
        for r in data.get("web", {}).get("results", [])
    ]
