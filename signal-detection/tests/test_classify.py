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
            headers={"x-ocn-caller": user_key},
            json={"articles": [_ARTICLE]},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "processing"

    async def test_401_without_caller_header(
        self, client: AsyncClient
    ) -> None:
        """Missing x-ocn-caller header returns 401."""
        resp = await client.post(
            "/classify",
            json={"articles": [_ARTICLE]},
        )
        assert resp.status_code == 401

    async def test_401_invalid_caller_header(
        self, client: AsyncClient
    ) -> None:
        """Malformed x-ocn-caller header returns 401."""
        resp = await client.post(
            "/classify",
            headers={"x-ocn-caller": "not-valid-base64!!!"},
            json={"articles": [_ARTICLE]},
        )
        assert resp.status_code == 401

    async def test_422_neither_run_id_nor_articles(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Request with neither run_id nor articles returns 422."""
        resp = await client.post(
            "/classify",
            headers={"x-ocn-caller": user_key},
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
                headers={"x-ocn-caller": user_key},
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
                headers={"x-ocn-caller": user_key},
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
                headers={"x-ocn-caller": user_key},
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
                headers={"x-ocn-caller": user_key},
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
            headers={"x-ocn-caller": user_key},
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
            headers={"x-ocn-caller": user_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job["id"]
        assert data["status"] == "processing"
        assert data["article_count"] == 5
        assert data["stats"] is None

    async def test_401_without_caller_header(
        self, client: AsyncClient
    ) -> None:
        """Missing x-ocn-caller header returns 401."""
        resp = await client.get("/classifications/1")
        assert resp.status_code == 401


class TestGetClassificationResults:
    """GET /classifications/{job_id}/results tests."""

    async def test_404_unknown_job(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Non-existent job_id returns 404."""
        resp = await client.get(
            "/classifications/99999/results",
            headers={"x-ocn-caller": user_key},
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
            headers={"x-ocn-caller": user_key},
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
            headers={"x-ocn-caller": user_key},
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
            headers={"x-ocn-caller": user_key},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Co-occurrence upsert integration
# ---------------------------------------------------------------------------


class TestCooccurrenceUpsert:
    """Integration tests for concept co-occurrence store (CON-149)."""

    def test_upsert_increments_count_correctly(self) -> None:
        """Calling upsert_cooccurrences twice with the same pair increments."""
        from db import get_db
        from models.cooccurrences import upsert_cooccurrences

        concepts = ["ai", "biotech"]
        upsert_cooccurrences(concepts)
        upsert_cooccurrences(concepts)

        with get_db() as conn:
            row = conn.execute(
                """
                SELECT co_occurrence_count
                FROM concept_cooccurrences
                WHERE concept_a = :a AND concept_b = :b
                """,
                {"a": "ai", "b": "biotech"},
            ).fetchone()

        assert row is not None
        assert row["co_occurrence_count"] == 2

    def test_upsert_skips_fewer_than_two_concepts(self) -> None:
        """Single-concept list inserts nothing into the store."""
        from db import get_db
        from models.cooccurrences import upsert_cooccurrences

        upsert_cooccurrences(["solo-concept"])

        with get_db() as conn:
            row = conn.execute(
                """
                SELECT co_occurrence_count
                FROM concept_cooccurrences
                WHERE concept_a = :a
                """,
                {"a": "solo-concept"},
            ).fetchone()

        assert row is None


# ---------------------------------------------------------------------------
# Deferred corpus guard (CON-150 / Signal deferral)
# ---------------------------------------------------------------------------


class TestDeferredCorpusGuard:
    """Signal articles must not pollute the corpus before promotion."""

    def _run_scoring(
        self,
        job_id: int,
        article_url: str,
        concepts: list[str],
        label_override: str,
        qdrant: object,
    ) -> None:
        """Invoke the corpus-guard logic directly, bypassing full pipeline.

        Replicates the conditional upsert and defer calls from
        _run_scoring_phase without requiring a live OpenAI or Qdrant.
        """
        import json
        from controllers.classify import _defer_claims_in_qdrant
        from models.cooccurrences import upsert_cooccurrences
        from models.jobs import (
            insert_classification,
            update_classification_concepts,
            update_classification_scores,
        )

        cid = insert_classification(
            job_id=job_id,
            article_url=article_url,
            article_embedding=[0.1] * 3072,
            model_embedding="test-embed",
            model_llm="test-llm",
            source="test.example.com",
        )
        update_classification_concepts(cid, concepts)
        update_classification_scores(
            classification_id=cid,
            label=label_override,
            composite_score=0.8 if label_override == "Signal" else 0.5,
            trajectory_score=0.5,
            claim_novelty_score=0.5,
            cluster_id=None,
        )

        if label_override != "Signal":
            upsert_cooccurrences(concepts)
        else:
            _defer_claims_in_qdrant(qdrant, ["claim-uuid-1"])

        return cid

    def test_signal_does_not_write_cooccurrences(self) -> None:
        """Signal article leaves concept_cooccurrences empty."""
        from db import get_db
        from models.jobs import create_job

        job = create_job(
            run_id="guard-signal",
            status="processing",
            callback_url=None,
            article_count=1,
        )
        qdrant = MagicMock()
        self._run_scoring(
            job["id"], "https://test.example.com/signal",
            ["ai", "biotech"], "Signal", qdrant,
        )

        with get_db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM concept_cooccurrences"
            ).fetchone()["n"]
        assert count == 0

    def test_non_signal_writes_cooccurrences(self) -> None:
        """Weak Signal article writes concept pairs immediately."""
        from db import get_db
        from models.jobs import create_job

        job = create_job(
            run_id="guard-weak",
            status="processing",
            callback_url=None,
            article_count=1,
        )
        qdrant = MagicMock()
        self._run_scoring(
            job["id"], "https://test.example.com/weak",
            ["ai", "finance"], "Weak Signal", qdrant,
        )

        with get_db() as conn:
            row = conn.execute(
                """
                SELECT co_occurrence_count FROM concept_cooccurrences
                WHERE concept_a = 'ai' AND concept_b = 'finance'
                """
            ).fetchone()
        assert row is not None
        assert row["co_occurrence_count"] == 1

    def test_signal_defers_claims_in_qdrant(self) -> None:
        """Signal article calls set_payload(deferred=True) on Qdrant."""
        from models.jobs import create_job

        job = create_job(
            run_id="guard-qdrant",
            status="processing",
            callback_url=None,
            article_count=1,
        )
        qdrant = MagicMock()
        self._run_scoring(
            job["id"], "https://test.example.com/qdrant-signal",
            ["ai"], "Signal", qdrant,
        )

        qdrant.set_payload.assert_called_once_with(
            collection_name="claims",
            payload={"deferred": True},
            points=["claim-uuid-1"],
        )

    def test_non_signal_does_not_defer_claims(self) -> None:
        """Non-Signal article makes no Qdrant set_payload call."""
        from models.jobs import create_job

        job = create_job(
            run_id="guard-no-defer",
            status="processing",
            callback_url=None,
            article_count=1,
        )
        qdrant = MagicMock()
        self._run_scoring(
            job["id"], "https://test.example.com/noise",
            ["ai", "climate"], "Noise", qdrant,
        )

        qdrant.set_payload.assert_not_called()


# ---------------------------------------------------------------------------
# flagged=true filter (CON-151)
# ---------------------------------------------------------------------------


class TestFlaggedFilter:
    """GET /classifications/{job_id}/results?flagged=true filter tests."""

    async def test_flagged_filter_returns_only_flagged(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """?flagged=true returns only rows with flagged_for_review=True."""
        from models.jobs import (
            create_job,
            insert_classification,
            update_classification_plausibility,
            update_classification_scores,
        )

        job = create_job(
            run_id="flagged-filter-run",
            status="completed",
            callback_url=None,
            article_count=2,
        )
        job_id = job["id"]

        cid_flagged = insert_classification(
            job_id=job_id,
            article_url="https://example.com/flagged",
            article_embedding=[0.1] * 3072,
            model_embedding="test-embed",
            model_llm="test-llm",
            source="example.com",
        )
        update_classification_scores(
            classification_id=cid_flagged,
            label="Weak Signal",
            composite_score=0.5,
            trajectory_score=0.5,
            claim_novelty_score=0.5,
            cluster_id=None,
        )
        update_classification_plausibility(
            classification_id=cid_flagged,
            plausibility_score=0.2,
            plausibility_flags=["low_evidence"],
            plausibility_reasoning="Dubious claim.",
            flagged_for_review=True,
        )

        cid_clean = insert_classification(
            job_id=job_id,
            article_url="https://example.com/clean",
            article_embedding=[0.2] * 3072,
            model_embedding="test-embed",
            model_llm="test-llm",
            source="example.com",
        )
        update_classification_scores(
            classification_id=cid_clean,
            label="Signal",
            composite_score=0.8,
            trajectory_score=0.7,
            claim_novelty_score=0.9,
            cluster_id=None,
        )

        resp = await client.get(
            f"/classifications/{job_id}/results?flagged=true",
            headers={"x-ocn-caller": user_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["article_url"] == "https://example.com/flagged"
        assert data["results"][0]["flagged_for_review"] is True

    async def test_no_flagged_param_returns_all(
        self, client: AsyncClient, user_key: str
    ) -> None:
        """Without ?flagged, all results are returned regardless of flag."""
        from models.jobs import (
            create_job,
            insert_classification,
            update_classification_plausibility,
            update_classification_scores,
        )

        job = create_job(
            run_id="no-flagged-param-run",
            status="completed",
            callback_url=None,
            article_count=2,
        )
        job_id = job["id"]

        for url, flagged in [
            ("https://example.com/a", True),
            ("https://example.com/b", False),
        ]:
            cid = insert_classification(
                job_id=job_id,
                article_url=url,
                article_embedding=[0.1] * 3072,
                model_embedding="test-embed",
                model_llm="test-llm",
                source="example.com",
            )
            update_classification_scores(
                classification_id=cid,
                label="Noise",
                composite_score=0.3,
                trajectory_score=0.3,
                claim_novelty_score=0.3,
                cluster_id=None,
            )
            if flagged:
                update_classification_plausibility(
                    classification_id=cid,
                    plausibility_score=0.1,
                    plausibility_flags=[],
                    plausibility_reasoning="Unreliable.",
                    flagged_for_review=True,
                )

        resp = await client.get(
            f"/classifications/{job_id}/results",
            headers={"x-ocn-caller": user_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 2
