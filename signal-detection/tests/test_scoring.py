"""Unit tests for scoring helpers (sub-score A, B, C + composite)."""
import json
import math
from unittest.mock import MagicMock

import pytest

from controllers.classify import (
    _apply_plausibility_downgrade,
    _assign_cluster,
    _assign_label,
    _call_plausibility_llm,
    _compute_bridge_score,
    _compute_claim_novelty,
    _compute_composite,
    _cosine_similarity,
    _defer_claims_in_qdrant,
)

# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    """_cosine_similarity returns expected values for known vectors."""

    def test_identical_vectors(self) -> None:
        """Identical vectors return similarity of 1.0."""
        v = [1.0, 0.0, 0.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        """Orthogonal vectors return similarity of 0.0."""
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        """Opposite vectors return similarity of -1.0."""
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self) -> None:
        """Zero vector produces 0.0 without raising."""
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# _assign_cluster
# ---------------------------------------------------------------------------


class TestAssignCluster:
    """_assign_cluster correctly identifies the nearest centroid."""

    def test_cold_start_no_clusters(self) -> None:
        """Empty cluster list triggers cold-start defaults."""
        cluster_id, score, low_conf = _assign_cluster([1.0, 0.0], [])
        assert cluster_id is None
        assert low_conf is True

    def test_cold_start_all_null_centroids(self) -> None:
        """Clusters with null centroid_vector trigger cold-start defaults."""
        clusters = [
            {"cluster_id": 1, "centroid_vector": None},
            {"cluster_id": 2, "centroid_vector": None},
        ]
        cluster_id, score, low_conf = _assign_cluster([1.0, 0.0], clusters)
        assert cluster_id is None
        assert low_conf is True

    def test_selects_nearest_cluster(self) -> None:
        """Returns the cluster whose centroid is closest to the embedding."""
        clusters = [
            {"cluster_id": 1, "centroid_vector": [1.0, 0.0]},
            {"cluster_id": 2, "centroid_vector": [0.0, 1.0]},
        ]
        embedding = [1.0, 0.0]
        cluster_id, traj_score, low_conf = _assign_cluster(
            embedding, clusters
        )
        assert cluster_id == 1
        assert traj_score == pytest.approx(0.0, abs=1e-5)
        assert low_conf is False

    def test_trajectory_score_is_one_minus_similarity(self) -> None:
        """trajectory_score = 1 - cosine_similarity, clamped to [0, 1]."""
        centroid = [1.0, 1.0]
        embedding = [1.0, 0.0]
        clusters = [{"cluster_id": 7, "centroid_vector": centroid}]
        _, score, _ = _assign_cluster(embedding, clusters)
        expected = 1.0 - _cosine_similarity(embedding, centroid)
        assert score == pytest.approx(expected, abs=1e-5)

    def test_low_confidence_flagged_below_threshold(self) -> None:
        """Low confidence flag raised when similarity < 0.3."""
        # Orthogonal vectors → similarity = 0.0 < 0.3
        clusters = [{"cluster_id": 3, "centroid_vector": [0.0, 1.0]}]
        embedding = [1.0, 0.0]
        _, _, low_conf = _assign_cluster(embedding, clusters)
        assert low_conf is True


# ---------------------------------------------------------------------------
# _compute_claim_novelty
# ---------------------------------------------------------------------------


class TestComputeClaimNovelty:
    """_compute_claim_novelty handles cold start and normal operation."""

    def test_empty_claim_ids_returns_cold_start(self) -> None:
        """No claims → cold-start score returned without Qdrant call."""
        qdrant = MagicMock()
        score = _compute_claim_novelty([], "article-id", qdrant, "ai_news")
        qdrant.retrieve.assert_not_called()
        assert score == pytest.approx(0.5)

    def test_qdrant_retrieve_failure_returns_cold_start(self) -> None:
        """Qdrant retrieve error → cold-start score, no exception."""
        qdrant = MagicMock()
        qdrant.retrieve.side_effect = RuntimeError("qdrant down")
        score = _compute_claim_novelty(
            ["claim-1"], "article-id", qdrant, "ai_news"
        )
        assert score == pytest.approx(0.5)

    def test_no_prior_claims_in_store_returns_cold_start(self) -> None:
        """NN search returns no results (cold store) → cold-start score."""
        qdrant = MagicMock()
        point = MagicMock()
        point.vector = [0.1, 0.2]
        qdrant.retrieve.return_value = [point]
        qdrant.query_points.return_value = MagicMock(points=[])
        score = _compute_claim_novelty(
            ["claim-1"], "article-id", qdrant, "ai_news"
        )
        assert score == pytest.approx(0.5)

    def test_mean_distance_computed_correctly(self) -> None:
        """Score is mean of (1 - similarity) across all NN results."""
        qdrant = MagicMock()
        point = MagicMock()
        point.vector = [0.1, 0.2]
        qdrant.retrieve.return_value = [point]

        nn1 = MagicMock()
        nn1.score = 0.8
        nn2 = MagicMock()
        nn2.score = 0.6
        qdrant.query_points.return_value = MagicMock(points=[nn1, nn2])

        score = _compute_claim_novelty(
            ["claim-1"], "article-id", qdrant, "ai_news"
        )
        # distances = [0.2, 0.4]; mean = 0.3
        assert score == pytest.approx(0.3, abs=1e-5)

    def test_own_article_excluded_from_search(self) -> None:
        """Qdrant search filter excludes own article and deferred claims."""
        from qdrant_client.models import FieldCondition, Filter

        qdrant = MagicMock()
        point = MagicMock()
        point.vector = [1.0, 0.0]
        qdrant.retrieve.return_value = [point]
        qdrant.query_points.return_value = MagicMock(points=[])

        _compute_claim_novelty(["c1"], "my-article-id", qdrant, "ai_news")

        _, kwargs = qdrant.query_points.call_args
        q_filter = kwargs.get("query_filter")
        assert isinstance(q_filter, Filter)
        assert q_filter.must_not is not None
        keys = {
            c.key
            for c in q_filter.must_not
            if isinstance(c, FieldCondition)
        }
        assert "article_qdrant_id" in keys
        assert "deferred" in keys


# ---------------------------------------------------------------------------
# _compute_claim_novelty — domain scoping
# ---------------------------------------------------------------------------


class TestDomainScopedClaimNovelty:
    """_compute_claim_novelty filters Qdrant search by domain."""

    def test_domain_filter_included_in_must(self) -> None:
        """Filter must list includes a domain condition matching the slug."""
        from qdrant_client.models import FieldCondition, Filter

        qdrant = MagicMock()
        point = MagicMock()
        point.vector = [1.0, 0.0]
        qdrant.retrieve.return_value = [point]
        qdrant.query_points.return_value = MagicMock(points=[])

        _compute_claim_novelty(["c1"], "article-id", qdrant, "ai_news")

        _, kwargs = qdrant.query_points.call_args
        q_filter = kwargs.get("query_filter")
        assert isinstance(q_filter, Filter)
        assert q_filter.must is not None
        must_keys = {
            c.key
            for c in q_filter.must
            if isinstance(c, FieldCondition)
        }
        assert "domain" in must_keys

    def test_different_domain_filter_respected(self) -> None:
        """Domain slug in filter matches the slug passed to the function."""
        from qdrant_client.models import FieldCondition, Filter

        qdrant = MagicMock()
        point = MagicMock()
        point.vector = [1.0, 0.0]
        qdrant.retrieve.return_value = [point]
        qdrant.query_points.return_value = MagicMock(points=[])

        _compute_claim_novelty(
            ["c1"], "article-id", qdrant, "biotech_research"
        )

        _, kwargs = qdrant.query_points.call_args
        q_filter = kwargs.get("query_filter")
        assert isinstance(q_filter, Filter)
        domain_conditions = [
            c for c in q_filter.must
            if isinstance(c, FieldCondition) and c.key == "domain"
        ]
        assert len(domain_conditions) == 1
        assert domain_conditions[0].match.value == "biotech_research"


# ---------------------------------------------------------------------------
# _compute_bridge_score
# ---------------------------------------------------------------------------


class TestComputeBridgeScore:
    """_compute_bridge_score returns correct values."""

    def test_single_concept_returns_none(self) -> None:
        """Fewer than 2 concepts → None (Phase 3 fallback)."""
        assert _compute_bridge_score(["ai"], {}) is None

    def test_zero_concepts_returns_none(self) -> None:
        """Empty concept list → None."""
        assert _compute_bridge_score([], {}) is None

    def test_rare_pair_scores_max(self) -> None:
        """Pair with count=0 scores 1.0 (maximum novelty)."""
        score = _compute_bridge_score(
            ["ai", "biotech"], {("ai", "biotech"): 0}
        )
        assert score == pytest.approx(1.0, abs=1e-5)

    def test_never_seen_pair_scores_max(self) -> None:
        """Pair absent from counts dict (cold start) scores 1.0."""
        score = _compute_bridge_score(["ai", "biotech"], {})
        assert score == pytest.approx(1.0, abs=1e-5)

    def test_common_pair_scores_low(self) -> None:
        """Pair seen 1000 times scores well below 0.5."""
        score = _compute_bridge_score(
            ["ai", "finance"], {("ai", "finance"): 1000}
        )
        expected = 1.0 / (1.0 + math.log(1001))
        assert score == pytest.approx(expected, abs=1e-5)
        assert score < 0.2

    def test_mean_across_multiple_pairs(self) -> None:
        """Score is mean across all concept pairs."""
        concepts = ["ai", "biotech", "finance"]
        counts = {
            ("ai", "biotech"): 0,
            ("ai", "finance"): 0,
            ("biotech", "finance"): 0,
        }
        score = _compute_bridge_score(concepts, counts)
        assert score == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------------------
# _compute_composite
# ---------------------------------------------------------------------------


class TestComputeComposite:
    """_compute_composite applies correct weights for Phase 3 and 4."""

    def test_phase3_weights_sum_correctly(self) -> None:
        """With equal sub-scores (no bridge) the composite equals that score."""
        score = _compute_composite(0.5, 0.5, bridge_score=None)
        assert score == pytest.approx(0.5, abs=1e-5)

    def test_phase3_trajectory_weight(self) -> None:
        """Pure trajectory deviation (no bridge) uses 0.40 weight."""
        score = _compute_composite(1.0, 0.0, bridge_score=None)
        assert score == pytest.approx(0.40, abs=1e-5)

    def test_phase3_claim_novelty_weight(self) -> None:
        """Pure claim novelty (no bridge) uses 0.60 weight."""
        score = _compute_composite(0.0, 1.0, bridge_score=None)
        assert score == pytest.approx(0.60, abs=1e-5)

    def test_phase3_default_bridge_is_none(self) -> None:
        """Omitting bridge_score defaults to Phase 3 behaviour."""
        p3 = _compute_composite(0.6, 0.4, bridge_score=None)
        p3_default = _compute_composite(0.6, 0.4)
        assert p3 == pytest.approx(p3_default, abs=1e-5)

    def test_phase4_trajectory_weight(self) -> None:
        """Pure trajectory (with bridge=0, novelty=0) uses 0.25 weight."""
        score = _compute_composite(1.0, 0.0, bridge_score=0.0)
        assert score == pytest.approx(0.25, abs=1e-5)

    def test_phase4_bridge_weight(self) -> None:
        """Pure bridge score (trajectory=0, novelty=0) uses 0.30 weight."""
        score = _compute_composite(0.0, 0.0, bridge_score=1.0)
        assert score == pytest.approx(0.30, abs=1e-5)

    def test_phase4_claim_novelty_weight(self) -> None:
        """Pure claim novelty (with bridge=0) uses 0.45 weight."""
        score = _compute_composite(0.0, 1.0, bridge_score=0.0)
        assert score == pytest.approx(0.45, abs=1e-5)

    def test_phase4_all_ones(self) -> None:
        """All sub-scores = 1.0 with Phase 4 weights sum to 1.0."""
        score = _compute_composite(1.0, 1.0, bridge_score=1.0)
        assert score == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------------------
# _assign_label
# ---------------------------------------------------------------------------


class TestAssignLabel:
    """_assign_label maps composite scores to the correct labels."""

    def test_high_signal(self) -> None:
        """Score >= 0.70 → 'Signal'."""
        assert _assign_label(0.70) == "Signal"
        assert _assign_label(1.00) == "Signal"

    def test_weak_signal(self) -> None:
        """Score in [0.40, 0.70) → 'Weak Signal'."""
        assert _assign_label(0.40) == "Weak Signal"
        assert _assign_label(0.69) == "Weak Signal"

    def test_noise(self) -> None:
        """Score < 0.40 → 'Noise'."""
        assert _assign_label(0.00) == "Noise"
        assert _assign_label(0.39) == "Noise"


# ---------------------------------------------------------------------------
# _apply_plausibility_downgrade
# ---------------------------------------------------------------------------


class TestApplyPlausibilityDowngrade:
    """_apply_plausibility_downgrade applies correct downgrade logic."""

    def test_signal_low_plausibility_downgraded(self) -> None:
        """Signal + plausibility < 0.30 → Weak Signal, flagged."""
        label, flagged = _apply_plausibility_downgrade("Signal", 0.10)
        assert label == "Weak Signal"
        assert flagged is True

    def test_weak_signal_low_plausibility_flagged(self) -> None:
        """Weak Signal + plausibility < 0.30 → stays Weak Signal, flagged."""
        label, flagged = _apply_plausibility_downgrade("Weak Signal", 0.20)
        assert label == "Weak Signal"
        assert flagged is True

    def test_signal_high_plausibility_unchanged(self) -> None:
        """Signal + plausibility >= 0.30 → unchanged, not flagged."""
        label, flagged = _apply_plausibility_downgrade("Signal", 0.80)
        assert label == "Signal"
        assert flagged is False

    def test_weak_signal_high_plausibility_unchanged(self) -> None:
        """Weak Signal + plausibility >= 0.30 → unchanged, not flagged."""
        label, flagged = _apply_plausibility_downgrade("Weak Signal", 0.50)
        assert label == "Weak Signal"
        assert flagged is False

    def test_boundary_at_threshold(self) -> None:
        """plausibility_score == 0.30 is not below threshold → no downgrade."""
        label, flagged = _apply_plausibility_downgrade("Signal", 0.30)
        assert label == "Signal"
        assert flagged is False

    def test_noise_label_unchanged(self) -> None:
        """Noise label is never passed to the filter but is handled safely."""
        label, flagged = _apply_plausibility_downgrade("Noise", 0.10)
        assert label == "Noise"
        assert flagged is False


# ---------------------------------------------------------------------------
# _call_plausibility_llm
# ---------------------------------------------------------------------------


class TestCallPlausibilityLlm:
    """_call_plausibility_llm parses responses and handles failures."""

    def _make_oai_mock(self, content: str) -> MagicMock:
        """Return a mocked OpenAI client returning *content*."""
        usage = MagicMock()
        usage.total_tokens = 500
        choice = MagicMock()
        choice.message.content = content
        response = MagicMock()
        response.choices = [choice]
        response.usage = usage
        oai = MagicMock()
        oai.chat.completions.create.return_value = response
        return oai

    def test_valid_json_returned(self) -> None:
        """Valid JSON response is parsed and returned as a dict."""
        payload = {
            "plausibility_score": 0.75,
            "flags": [],
            "reasoning": "Credible sources.",
        }
        oai = self._make_oai_mock(json.dumps(payload))
        result = _call_plausibility_llm(
            oai, "test-model", "Title", "Body", 0.60
        )
        assert result is not None
        assert result["plausibility_score"] == pytest.approx(0.75)
        assert result["flags"] == []
        assert result["reasoning"] == "Credible sources."

    def test_invalid_json_returns_none(self) -> None:
        """Malformed JSON response → returns None without raising."""
        oai = self._make_oai_mock("NOT JSON AT ALL")
        result = _call_plausibility_llm(
            oai, "test-model", "Title", "Body", 0.60
        )
        assert result is None

    def test_llm_exception_returns_none(self) -> None:
        """LLM call raising an exception → returns None without raising."""
        oai = MagicMock()
        oai.chat.completions.create.side_effect = RuntimeError("api down")
        result = _call_plausibility_llm(
            oai, "test-model", "Title", "Body", 0.60
        )
        assert result is None

    def test_flags_from_response(self) -> None:
        """Flags array from LLM response is preserved."""
        payload = {
            "plausibility_score": 0.15,
            "flags": ["conspiracy_framing", "no_credible_mechanism"],
            "reasoning": "Suspicious framing.",
        }
        oai = self._make_oai_mock(json.dumps(payload))
        result = _call_plausibility_llm(
            oai, "test-model", "Title", "Body", 0.65
        )
        assert result is not None
        assert "conspiracy_framing" in result["flags"]


# ---------------------------------------------------------------------------
# _defer_claims_in_qdrant
# ---------------------------------------------------------------------------


class TestDeferClaimsInQdrant:
    """_defer_claims_in_qdrant marks claim vectors deferred in Qdrant."""

    def test_empty_ids_no_qdrant_call(self) -> None:
        """Empty claim list makes no Qdrant call."""
        qdrant = MagicMock()
        _defer_claims_in_qdrant(qdrant, [])
        qdrant.set_payload.assert_not_called()

    def test_sets_deferred_true_on_given_ids(self) -> None:
        """set_payload called with deferred=True for all provided IDs."""
        qdrant = MagicMock()
        _defer_claims_in_qdrant(qdrant, ["id-1", "id-2"])
        qdrant.set_payload.assert_called_once_with(
            collection_name="claims",
            payload={"deferred": True},
            points=["id-1", "id-2"],
        )

    def test_qdrant_failure_does_not_raise(self) -> None:
        """Qdrant error is swallowed; no exception propagates."""
        qdrant = MagicMock()
        qdrant.set_payload.side_effect = RuntimeError("qdrant down")
        _defer_claims_in_qdrant(qdrant, ["id-1"])  # must not raise


# ---------------------------------------------------------------------------
# domain → cluster lookup path
# ---------------------------------------------------------------------------


class TestDomainClusterLookup:
    """Domain slug is passed correctly through the scoring pipeline."""

    def test_run_scoring_phase_uses_domain_not_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_run_scoring_phase calls get_clusters_for_domain with domain, not
        the article source field.
        """
        import asyncio
        from unittest.mock import AsyncMock, patch

        captured: list[str] = []

        def fake_get_clusters(domain: str) -> list:
            captured.append(domain)
            return []

        # Minimal DB row shape expected by the scoring loop
        fake_row = {
            "id": 1,
            "article_url": "https://example.com/article",
            "source": "SiliconANGLE",
            "article_embedding": [1.0, 0.0],
            "concepts": [],
            "claim_ids": [],
        }

        import controllers.classify as classify_mod

        with (
            patch.object(
                classify_mod, "get_clusters_for_domain", side_effect=fake_get_clusters
            ),
            patch("db.get_db") as mock_get_db,
            patch.object(classify_mod, "_compute_claim_novelty", return_value=0.5),
            patch.object(classify_mod, "get_cooccurrence_counts", return_value={}),
            patch.object(classify_mod, "update_classification_scores"),
            patch.object(classify_mod, "update_classification_plausibility"),
            patch.object(classify_mod, "_langfuse_client", return_value=None),
        ):
            conn_mock = MagicMock()
            conn_mock.execute.return_value.fetchall.return_value = [fake_row]
            mock_get_db.return_value.__enter__ = MagicMock(return_value=conn_mock)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            qdrant = MagicMock()
            asyncio.run(
                classify_mod._run_scoring_phase(
                    job_id=1,
                    qdrant=qdrant,
                    articles=[],
                    domain="ai_news",
                )
            )

        assert captured == ["ai_news"], (
            f"Expected get_clusters_for_domain('ai_news') but got {captured!r}"
        )

    def test_run_scoring_phase_does_not_use_source_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """source field ('SiliconANGLE') is never passed to cluster lookup."""
        import asyncio
        from unittest.mock import patch

        captured: list[str] = []

        def fake_get_clusters(domain: str) -> list:
            captured.append(domain)
            return []

        fake_row = {
            "id": 1,
            "article_url": "https://example.com/article",
            "source": "SiliconANGLE",
            "article_embedding": [1.0, 0.0],
            "concepts": [],
            "claim_ids": [],
        }

        import controllers.classify as classify_mod

        with (
            patch.object(
                classify_mod, "get_clusters_for_domain", side_effect=fake_get_clusters
            ),
            patch("db.get_db") as mock_get_db,
            patch.object(classify_mod, "_compute_claim_novelty", return_value=0.5),
            patch.object(classify_mod, "get_cooccurrence_counts", return_value={}),
            patch.object(classify_mod, "update_classification_scores"),
            patch.object(classify_mod, "update_classification_plausibility"),
            patch.object(classify_mod, "_langfuse_client", return_value=None),
        ):
            conn_mock = MagicMock()
            conn_mock.execute.return_value.fetchall.return_value = [fake_row]
            mock_get_db.return_value.__enter__ = MagicMock(return_value=conn_mock)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

            qdrant = MagicMock()
            asyncio.run(
                classify_mod._run_scoring_phase(
                    job_id=1,
                    qdrant=qdrant,
                    articles=[],
                    domain="ai_news",
                )
            )

        assert "SiliconANGLE" not in captured


# ---------------------------------------------------------------------------
# Domain-scoped co-occurrence repository
# ---------------------------------------------------------------------------


class TestDomainScopedCooccurrences:
    """upsert_cooccurrences and get_cooccurrence_counts are domain-scoped."""

    def test_upsert_cooccurrences_passes_domain(self) -> None:
        """Domain slug is included in the INSERT params."""
        from unittest.mock import patch

        from models.cooccurrences import upsert_cooccurrences

        conn_mock = MagicMock()
        with patch("models.cooccurrences.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(
                return_value=conn_mock
            )
            mock_get_db.return_value.__exit__ = MagicMock(
                return_value=False
            )
            upsert_cooccurrences(["ai", "biotech"], "ai_news")

        assert conn_mock.execute.called
        # call_args[0] is the positional args tuple: (sql, params_dict)
        params = conn_mock.execute.call_args[0][1]
        assert params.get("domain") == "ai_news"

    def test_get_cooccurrence_counts_filters_by_domain(self) -> None:
        """Domain slug is added to the WHERE clause params."""
        from unittest.mock import patch

        from models.cooccurrences import get_cooccurrence_counts

        conn_mock = MagicMock()
        conn_mock.execute.return_value.fetchall.return_value = []
        with patch("models.cooccurrences.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__ = MagicMock(
                return_value=conn_mock
            )
            mock_get_db.return_value.__exit__ = MagicMock(
                return_value=False
            )
            get_cooccurrence_counts(
                [("ai", "biotech")], "biotech_research"
            )

        assert conn_mock.execute.called
        params = conn_mock.execute.call_args[0][1]
        assert params.get("domain") == "biotech_research"
