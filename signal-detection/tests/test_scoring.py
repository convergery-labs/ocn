"""Unit tests for scoring helpers (sub-score A, B, C + composite)."""
import math
from unittest.mock import MagicMock

import pytest

from controllers.classify import (
    _assign_cluster,
    _assign_label,
    _compute_bridge_score,
    _compute_claim_novelty,
    _compute_composite,
    _cosine_similarity,
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
        score = _compute_claim_novelty([], "article-id", qdrant)
        qdrant.retrieve.assert_not_called()
        assert score == pytest.approx(0.5)

    def test_qdrant_retrieve_failure_returns_cold_start(self) -> None:
        """Qdrant retrieve error → cold-start score, no exception."""
        qdrant = MagicMock()
        qdrant.retrieve.side_effect = RuntimeError("qdrant down")
        score = _compute_claim_novelty(
            ["claim-1"], "article-id", qdrant
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
            ["claim-1"], "article-id", qdrant
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
            ["claim-1"], "article-id", qdrant
        )
        # distances = [0.2, 0.4]; mean = 0.3
        assert score == pytest.approx(0.3, abs=1e-5)

    def test_own_article_excluded_from_search(self) -> None:
        """Qdrant search is called with a filter excluding the article."""
        from qdrant_client.models import Filter

        qdrant = MagicMock()
        point = MagicMock()
        point.vector = [1.0, 0.0]
        qdrant.retrieve.return_value = [point]
        qdrant.query_points.return_value = MagicMock(points=[])

        _compute_claim_novelty(["c1"], "my-article-id", qdrant)

        _, kwargs = qdrant.query_points.call_args
        q_filter = kwargs.get("query_filter")
        assert q_filter is not None
        assert isinstance(q_filter, Filter)


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
