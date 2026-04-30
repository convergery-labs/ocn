"""Async client for the internal news-retrieval service."""
import os
from typing import Optional

import httpx


class NewsRetrievalClient:
    """Wraps async HTTP calls to the news-retrieval service."""

    def __init__(self) -> None:
        """Initialise client from environment variables."""
        base_url = os.environ["NEWS_RETRIEVAL_URL"]
        api_key = os.environ["NEWS_RETRIEVAL_API_KEY"]
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"x-ocn-caller": api_key},
        )

    async def create_run(
        self,
        domain_slug: str,
        days_back: int,
        focus: Optional[str],
        callback_url: Optional[str],
    ) -> dict:
        """POST /run and return the response body.

        Returns the raw response dict. HTTP status is accessible via the
        caller inspecting response status; this method raises on non-2xx.
        """
        payload: dict = {
            "domain": domain_slug,
            "days_back": days_back,
        }
        if focus is not None:
            payload["focus"] = focus
        if callback_url is not None:
            payload["callback_url"] = callback_url
        response = await self._client.post("/run", json=payload)
        response.raise_for_status()
        return {"status_code": response.status_code, "body": response.json()}

    async def get_articles(self, run_id: int) -> list[dict]:
        """GET /runs/{run_id}/articles and return the article list."""
        response = await self._client.get(f"/runs/{run_id}/articles")
        response.raise_for_status()
        data = response.json()
        return data.get("articles", data) if isinstance(data, dict) else data

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
