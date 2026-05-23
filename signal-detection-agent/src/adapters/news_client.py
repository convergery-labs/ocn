"""HTTP client for the news-retrieval service."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECS = 10
_FETCH_PAGE_SIZE = 100


class NewsRetrievalError(Exception):
    """Raised when news-retrieval returns an unexpected response."""


def _headers() -> dict[str, str]:
    return {"x-ocn-caller": config.NEWS_RETRIEVAL_SERVICE_CALLER}


async def trigger_run(domain: str) -> int:
    """POST /run to news-retrieval; return run_id.

    Handles 202 (new run), 200 (cache hit), and 409 (conflict).
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{config.NEWS_RETRIEVAL_URL}/run",
                json={"domain": domain},
                headers=_headers(),
            )
    except httpx.HTTPError as exc:
        raise NewsRetrievalError(f"news-retrieval unreachable: {exc}") from exc

    if resp.status_code == 200:
        return int(resp.json()["id"])
    if resp.status_code == 202:
        return int(resp.json()["run_id"])
    if resp.status_code == 409:
        return int(resp.json()["detail"]["run_id"])
    raise NewsRetrievalError(
        f"POST /run returned {resp.status_code}: {resp.text}"
    )


async def fetch_latest_run(domain: str) -> int | None:
    """GET /runs?domain=<slug>&status=completed&limit=1; return run_id or None."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{config.NEWS_RETRIEVAL_URL}/runs",
                params={"domain": domain, "status": "completed", "limit": 1},
                headers=_headers(),
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise NewsRetrievalError(f"news-retrieval unreachable: {exc}") from exc
    runs = resp.json().get("runs") or []
    return int(runs[0]["id"]) if runs else None


async def poll_run_until_done(run_id: int) -> None:
    """Poll GET /runs/{run_id} until status is completed or failed."""
    elapsed = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                resp = await client.get(
                    f"{config.NEWS_RETRIEVAL_URL}/runs/{run_id}",
                    headers=_headers(),
                )
                resp.raise_for_status()
                status = resp.json().get("status")
            except Exception as exc:
                raise NewsRetrievalError(
                    f"Failed to poll news-retrieval run {run_id}: {exc}"
                ) from exc

            if status == "completed":
                return
            if status == "failed":
                raise NewsRetrievalError(f"news-retrieval run {run_id} failed")
            if elapsed >= config.PIPELINE_POLL_TIMEOUT_SECS:
                raise NewsRetrievalError(
                    f"Timed out waiting for news-retrieval run {run_id}"
                )
            await asyncio.sleep(_POLL_INTERVAL_SECS)
            elapsed += _POLL_INTERVAL_SECS


async def get_run_articles(run_id: int) -> list[dict[str, Any]]:
    """Paginate GET /runs/{run_id}/articles; return all articles with body."""
    articles: list[dict[str, Any]] = []
    cursor: str | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: dict[str, Any] = {"include_body": "true", "limit": _FETCH_PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            try:
                resp = await client.get(
                    f"{config.NEWS_RETRIEVAL_URL}/runs/{run_id}/articles",
                    params=params,
                    headers=_headers(),
                )
                resp.raise_for_status()
            except Exception as exc:
                raise NewsRetrievalError(
                    f"Failed to fetch articles for run {run_id}: {exc}"
                ) from exc
            data = resp.json()
            articles.extend(data.get("articles", []))
            cursor = data.get("next_cursor")
            if not cursor:
                break
    return articles
