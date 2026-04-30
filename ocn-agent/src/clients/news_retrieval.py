"""Async client for the internal news-retrieval service."""
import os

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

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
