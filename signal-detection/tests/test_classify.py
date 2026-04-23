"""Tests for POST /classify and GET /classifications/* endpoints."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from models.jobs import create_job

_ARTICLE = {"url": "https://example.com", "title": "T", "body": "B"}


def _mock_news_retrieval_ok():
    """Patch httpx.AsyncClient to return 200 for news-retrieval."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return patch(
        "controllers.classify.httpx.AsyncClient",
        return_value=mock_client,
    )


def _mock_news_retrieval_not_found():
    """Patch httpx.AsyncClient to return 404 for news-retrieval."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)
    return patch(
        "controllers.classify.httpx.AsyncClient",
        return_value=mock_client,
    )


class TestPostClassifyModeB:
    """Direct-article (Mode B) submission tests."""

    async def test_202_on_valid_submit(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Valid Mode B request returns 202 with job_id and status."""
        resp = await client.post(
            "/classify",
            headers={"Authorization": f"Bearer {user_key}"},
            json={"articles": [_ARTICLE]},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "processing"

    async def test_422_without_auth(
        self, client: AsyncClient
    ) -> None:
        """Missing Authorization header returns 422 (required header)."""
        resp = await client.post(
            "/classify",
            json={"articles": [_ARTICLE]},
        )
        assert resp.status_code == 422

    async def test_401_invalid_token(
        self, client: AsyncClient
    ) -> None:
        """Unknown token returns 401."""
        resp = await client.post(
            "/classify",
            headers={"Authorization": "Bearer bad-token"},
            json={"articles": [_ARTICLE]},
        )
        assert resp.status_code == 401

    async def test_422_neither_run_id_nor_articles(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Request with neither run_id nor articles returns 422."""
        resp = await client.post(
            "/classify",
            headers={"Authorization": f"Bearer {user_key}"},
            json={},
        )
        assert resp.status_code == 422

    async def test_422_both_run_id_and_articles(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Request with both run_id and articles returns 422."""
        with _mock_news_retrieval_ok():
            resp = await client.post(
                "/classify",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"run_id": 1, "articles": [_ARTICLE]},
            )
        assert resp.status_code == 422


class TestPostClassifyModeA:
    """news-retrieval run_id (Mode A) submission tests."""

    async def test_202_on_valid_run_id(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Valid run_id that exists in news-retrieval returns 202."""
        with _mock_news_retrieval_ok():
            resp = await client.post(
                "/classify",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"run_id": 42},
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "processing"

    async def test_404_unknown_run_id(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """run_id not found in news-retrieval returns 404."""
        with _mock_news_retrieval_not_found():
            resp = await client.post(
                "/classify",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"run_id": 999},
            )
        assert resp.status_code == 404

    async def test_409_duplicate_run_id(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """A second submit for the same run_id returns 409."""
        create_job(
            run_id="77",
            status="processing",
            callback_url=None,
            article_count=0,
        )
        with _mock_news_retrieval_ok():
            resp = await client.post(
                "/classify",
                headers={"Authorization": f"Bearer {user_key}"},
                json={"run_id": 77},
            )
        assert resp.status_code == 409


class TestGetClassification:
    """GET /classifications/{job_id} tests."""

    async def test_404_unknown_job(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Non-existent job_id returns 404."""
        resp = await client.get(
            "/classifications/99999",
            headers={"Authorization": f"Bearer {user_key}"},
        )
        assert resp.status_code == 404

    async def test_returns_job_fields(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Existing job returns expected fields."""
        job = create_job(
            run_id="test-run",
            status="processing",
            callback_url=None,
            article_count=5,
        )
        resp = await client.get(
            f"/classifications/{job['id']}",
            headers={"Authorization": f"Bearer {user_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job["id"]
        assert data["status"] == "processing"
        assert data["article_count"] == 5
        assert data["stats"] is None

    async def test_422_without_auth(
        self, client: AsyncClient
    ) -> None:
        """Missing Authorization header returns 422 (required header)."""
        resp = await client.get("/classifications/1")
        assert resp.status_code == 422


class TestGetClassificationResults:
    """GET /classifications/{job_id}/results tests."""

    async def test_404_unknown_job(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Non-existent job_id returns 404."""
        resp = await client.get(
            "/classifications/99999/results",
            headers={"Authorization": f"Bearer {user_key}"},
        )
        assert resp.status_code == 404

    async def test_empty_results(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Job with no classifications returns empty list."""
        job = create_job(
            run_id="empty-run",
            status="completed",
            callback_url=None,
            article_count=0,
        )
        resp = await client.get(
            f"/classifications/{job['id']}/results",
            headers={"Authorization": f"Bearer {user_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["next_cursor"] is None

    async def test_422_invalid_limit(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """limit outside [1, 100] returns 422."""
        job = create_job(
            run_id="limit-run",
            status="completed",
            callback_url=None,
            article_count=0,
        )
        resp = await client.get(
            f"/classifications/{job['id']}/results?limit=200",
            headers={"Authorization": f"Bearer {user_key}"},
        )
        assert resp.status_code == 422

    async def test_422_invalid_cursor(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Malformed cursor returns 422."""
        job = create_job(
            run_id="cursor-run",
            status="completed",
            callback_url=None,
            article_count=0,
        )
        resp = await client.get(
            f"/classifications/{job['id']}/results?cursor=notbase64!!!",
            headers={"Authorization": f"Bearer {user_key}"},
        )
        assert resp.status_code == 422
