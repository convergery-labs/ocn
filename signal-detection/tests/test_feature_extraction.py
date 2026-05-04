"""Tests for the feature extraction pipeline (CON-137).

Covers: MinHash dedup, language filter, article embedding → Qdrant,
LLM claim extraction, claim embedding → Qdrant, and claim Postgres
storage.  QdrantClient and OpenAI are mocked at the boundary; Postgres
is the real test DB managed by the session-scoped conftest fixtures.
"""
import json
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

from controllers.classify import (
    _dedup_indices,
    _detect_language,
    _extract_claims,
    _run_feature_extraction,
)
from db import get_db
from models.jobs import create_job

_EN_BODY = (
    "Scientists have discovered a new species of deep-sea fish near the "
    "Mariana Trench.  The creature exhibits bioluminescent properties that "
    "have not been observed in any previously catalogued organism."
)
_FR_BODY = (
    "Les scientifiques ont découvert une nouvelle espèce de poisson des "
    "grands fonds près de la fosse des Mariannes."
)

_ARTICLE_EN = {
    "url": "https://example.com/en-article",
    "title": "Deep-sea discovery",
    "body": _EN_BODY,
    "source": "example.com",
    "published": "2026-01-01",
}
_ARTICLE_FR = {
    "url": "https://example.com/fr-article",
    "title": "Découverte",
    "body": _FR_BODY,
    "source": "example.com",
    "published": "2026-01-02",
}
# Near-duplicate of _ARTICLE_EN — differs by one word at the end
_ARTICLE_DUP = {
    "url": "https://example.com/dup-article",
    "title": "Deep-sea discovery dup",
    "body": _EN_BODY + " Amazing.",
    "source": "example.com",
    "published": "2026-01-03",
}

_FAKE_ARTICLE_EMBEDDING = [0.1] * 3072
_FAKE_CLAIM_EMBEDDING = [0.2] * 1536
_CLAIMS_JSON = '["Claim A.", "Claim B.", "Claim C."]'
_CLAIM_MODEL = "openai/text-embedding-3-small"


def _mock_openai(claim_json: str = _CLAIMS_JSON):
    """Return a mock OpenAI instance with preset embedding + chat responses."""
    oai = MagicMock()
    # embeddings.create returns different sized vectors depending on call
    embed_resp_article = MagicMock()
    embed_resp_article.data = [
        MagicMock(embedding=_FAKE_ARTICLE_EMBEDDING)
    ]
    embed_resp_claim = MagicMock()
    embed_resp_claim.data = [
        MagicMock(embedding=_FAKE_CLAIM_EMBEDDING),
        MagicMock(embedding=_FAKE_CLAIM_EMBEDDING),
        MagicMock(embedding=_FAKE_CLAIM_EMBEDDING),
    ]

    def _create_embedding(model, input):  # noqa: A002
        if isinstance(input, list) and len(input) > 1:
            # claim batch
            return MagicMock(
                data=[
                    MagicMock(embedding=_FAKE_CLAIM_EMBEDDING)
                    for _ in input
                ]
            )
        return embed_resp_article

    oai.embeddings.create.side_effect = _create_embedding

    chat_msg = MagicMock()
    chat_msg.content = claim_json
    chat_choice = MagicMock()
    chat_choice.message = chat_msg
    chat_resp = MagicMock()
    chat_resp.choices = [chat_choice]
    oai.chat.completions.create.return_value = chat_resp
    return oai


def _mock_qdrant():
    """Return a mock QdrantClient instance."""
    qdrant = MagicMock()
    qdrant.get_collections.return_value = MagicMock(collections=[])
    return qdrant


# ---------------------------------------------------------------------------
# Unit — _dedup_indices
# ---------------------------------------------------------------------------

class TestDedupIndices:
    """_dedup_indices correctly filters near-duplicate articles."""

    def test_identical_bodies_deduped(self) -> None:
        """Two articles with identical bodies → only first kept."""
        articles = [
            {"body": "word " * 50},
            {"body": "word " * 50},
        ]
        keep = _dedup_indices(articles)
        assert keep == [0]

    def test_distinct_bodies_both_kept(self) -> None:
        """Two articles with entirely different bodies → both kept."""
        articles = [
            {"body": "alpha beta gamma delta epsilon " * 10},
            {"body": "zeta eta theta iota kappa " * 10},
        ]
        keep = _dedup_indices(articles)
        assert keep == [0, 1]

    def test_near_duplicate_skipped(self) -> None:
        """Near-duplicate article (Jaccard > 0.85) is skipped."""
        base_body = _EN_BODY
        dup_body = _EN_BODY + " Extra sentence."
        articles = [
            {"url": "a", "body": base_body},
            {"url": "b", "body": dup_body},
        ]
        keep = _dedup_indices(articles)
        assert len(keep) == 1
        assert keep[0] == 0


# ---------------------------------------------------------------------------
# Unit — _detect_language
# ---------------------------------------------------------------------------

class TestDetectLanguage:
    """_detect_language returns ISO 639-1 codes without raising."""

    def test_english_text(self) -> None:
        """English text is detected as 'en'."""
        assert _detect_language(_EN_BODY) == "en"

    def test_empty_string_returns_unknown(self) -> None:
        """Empty string returns 'unknown' without raising."""
        result = _detect_language("")
        assert result == "unknown"

    def test_garbage_returns_unknown(self) -> None:
        """Unparseable garbage returns 'unknown'."""
        result = _detect_language("!!!###$$$%%%")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Unit — _extract_claims
# ---------------------------------------------------------------------------

class TestExtractClaims:
    """_extract_claims handles happy path and error cases."""

    def test_valid_json_array(self) -> None:
        """LLM returns a valid JSON array → list of claim strings."""
        oai = _mock_openai(_CLAIMS_JSON)
        claims = _extract_claims(oai, "model", "article body")
        assert claims == ["Claim A.", "Claim B.", "Claim C."]

    def test_malformed_json_returns_empty(self) -> None:
        """LLM returns malformed JSON → empty list, no exception."""
        oai = _mock_openai("not valid json at all")
        claims = _extract_claims(oai, "model", "article body")
        assert claims == []

    def test_json_object_not_array_returns_empty(self) -> None:
        """LLM returns a JSON object instead of array → empty list."""
        oai = _mock_openai('{"claim": "value"}')
        claims = _extract_claims(oai, "model", "article body")
        assert claims == []

    def test_empty_string_response_returns_empty(self) -> None:
        """LLM returns empty string → empty list, no exception."""
        oai = _mock_openai("")
        claims = _extract_claims(oai, "model", "article body")
        assert claims == []


# ---------------------------------------------------------------------------
# Integration — _run_feature_extraction
# ---------------------------------------------------------------------------

class TestRunFeatureExtraction:
    """End-to-end pipeline tests with mocked Qdrant + OpenAI + real DB."""

    @pytest.fixture(autouse=True)
    def job(self, db_setup: None):
        """Create a classification job for each test."""
        return create_job(
            run_id=str(uuid.uuid4()),
            status="processing",
            callback_url=None,
            article_count=3,
        )

    @pytest.mark.asyncio
    async def test_article_upserted_to_qdrant(self, job) -> None:
        """Article embedding is upserted to the 'articles' Qdrant collection."""
        qdrant = _mock_qdrant()
        oai = _mock_openai()
        with (
            patch("controllers.classify.QdrantClient", return_value=qdrant),
            patch("controllers.classify.OpenAI", return_value=oai),
        ):
            await _run_feature_extraction(job["id"], [_ARTICLE_EN])

        upsert_calls = [
            c for c in qdrant.upsert.call_args_list
            if c.kwargs.get("collection_name") == "articles"
            or (c.args and c.args[0] == "articles")
        ]
        assert len(upsert_calls) == 1
        points = (
            upsert_calls[0].kwargs.get("points")
            or upsert_calls[0].args[1]
        )
        assert len(points) == 1
        payload = points[0].payload
        assert payload["url"] == _ARTICLE_EN["url"]
        assert payload["domain"] == _ARTICLE_EN["source"]
        assert payload["published_date"] == _ARTICLE_EN["published"]
        assert payload["label"] is None

    @pytest.mark.asyncio
    async def test_near_duplicate_skipped(self, job) -> None:
        """Near-duplicate article is skipped; only one article reaches Qdrant."""
        qdrant = _mock_qdrant()
        oai = _mock_openai()
        with (
            patch("controllers.classify.QdrantClient", return_value=qdrant),
            patch("controllers.classify.OpenAI", return_value=oai),
        ):
            await _run_feature_extraction(
                job["id"], [_ARTICLE_EN, _ARTICLE_DUP]
            )

        article_upsert_calls = [
            c for c in qdrant.upsert.call_args_list
            if c.kwargs.get("collection_name") == "articles"
            or (c.args and c.args[0] == "articles")
        ]
        assert len(article_upsert_calls) == 1
        points = (
            article_upsert_calls[0].kwargs.get("points")
            or article_upsert_calls[0].args[1]
        )
        assert len(points) == 1

    @pytest.mark.asyncio
    async def test_non_english_article_skipped(self, job) -> None:
        """Non-English article does not reach Qdrant or the DB."""
        qdrant = _mock_qdrant()
        oai = _mock_openai()
        with (
            patch("controllers.classify.QdrantClient", return_value=qdrant),
            patch("controllers.classify.OpenAI", return_value=oai),
        ):
            await _run_feature_extraction(
                job["id"], [_ARTICLE_FR]
            )

        qdrant.upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_claims_upserted_to_qdrant(self, job) -> None:
        """Extracted claims are upserted to the 'claims' Qdrant collection."""
        qdrant = _mock_qdrant()
        oai = _mock_openai()
        with (
            patch("controllers.classify.QdrantClient", return_value=qdrant),
            patch("controllers.classify.OpenAI", return_value=oai),
        ):
            await _run_feature_extraction(job["id"], [_ARTICLE_EN])

        claim_upsert_calls = [
            c for c in qdrant.upsert.call_args_list
            if c.kwargs.get("collection_name") == "claims"
            or (c.args and c.args[0] == "claims")
        ]
        assert len(claim_upsert_calls) == 1
        points = (
            claim_upsert_calls[0].kwargs.get("points")
            or claim_upsert_calls[0].args[1]
        )
        assert len(points) == 3  # 3 claims from _CLAIMS_JSON
        expected_article_qdrant_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, _ARTICLE_EN["url"])
        )
        for point in points:
            assert point.payload["article_qdrant_id"] == expected_article_qdrant_id

    @pytest.mark.asyncio
    async def test_claims_stored_in_postgres(self, job) -> None:
        """Claim rows are inserted into the claims Postgres table."""
        qdrant = _mock_qdrant()
        oai = _mock_openai()
        with (
            patch("controllers.classify.QdrantClient", return_value=qdrant),
            patch("controllers.classify.OpenAI", return_value=oai),
        ):
            await _run_feature_extraction(job["id"], [_ARTICLE_EN])

        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT c.claim_text, c.embedding_model
                FROM claims c
                JOIN classifications cl ON cl.id = c.classification_id
                WHERE cl.job_id = :job_id
                """,
                {"job_id": job["id"]},
            ).fetchall()

        assert len(rows) == 3
        claim_texts = {r["claim_text"] for r in rows}
        assert claim_texts == {"Claim A.", "Claim B.", "Claim C."}
        for row in rows:
            assert row["embedding_model"] == _CLAIM_MODEL

    @pytest.mark.asyncio
    async def test_malformed_claim_json_no_claims_stored(self, job) -> None:
        """Malformed LLM JSON → pipeline completes; no claim rows inserted."""
        qdrant = _mock_qdrant()
        oai = _mock_openai("this is not json")
        with (
            patch("controllers.classify.QdrantClient", return_value=qdrant),
            patch("controllers.classify.OpenAI", return_value=oai),
        ):
            await _run_feature_extraction(job["id"], [_ARTICLE_EN])

        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT c.id FROM claims c
                JOIN classifications cl ON cl.id = c.classification_id
                WHERE cl.job_id = :job_id
                """,
                {"job_id": job["id"]},
            ).fetchall()

        assert rows == []

    @pytest.mark.asyncio
    async def test_langfuse_trace_emitted_when_key_set(self, job) -> None:
        """When LANGFUSE_PUBLIC_KEY is set, a Langfuse trace is started."""
        qdrant = _mock_qdrant()
        oai = _mock_openai()
        mock_lf_instance = MagicMock()
        mock_lf_class = MagicMock(return_value=mock_lf_instance)
        with (
            patch("controllers.classify.QdrantClient", return_value=qdrant),
            patch("controllers.classify.OpenAI", return_value=oai),
            patch.dict(os.environ, {"LANGFUSE_PUBLIC_KEY": "test-key"}),
            patch("langfuse.Langfuse", mock_lf_class),
        ):
            await _run_feature_extraction(job["id"], [_ARTICLE_EN])

        mock_lf_instance.trace.assert_called_once()
        call_kwargs = mock_lf_instance.trace.call_args
        assert call_kwargs.kwargs.get("name") == "feature-extraction"

    @pytest.mark.asyncio
    async def test_no_langfuse_trace_without_key(self, job) -> None:
        """Without LANGFUSE_PUBLIC_KEY, no Langfuse client is created."""
        qdrant = _mock_qdrant()
        oai = _mock_openai()
        env = {k: v for k, v in os.environ.items() if k != "LANGFUSE_PUBLIC_KEY"}
        mock_lf_class = MagicMock()
        with (
            patch("controllers.classify.QdrantClient", return_value=qdrant),
            patch("controllers.classify.OpenAI", return_value=oai),
            patch.dict(os.environ, env, clear=True),
            patch("langfuse.Langfuse", mock_lf_class),
        ):
            await _run_feature_extraction(job["id"], [_ARTICLE_EN])

        mock_lf_class.assert_not_called()
