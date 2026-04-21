"""Unit tests for ``superbrain.engine.similarity``."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from superbrain.engine.clustering import (
    cluster_teams,
    merge_opponent_clusters,
)
from superbrain.engine.similarity import (
    SimilarityMatrix,
    build_similarity_matrix,
    find_similar_team_seasons,
    frobenius_similarity,
    similarity_threshold,
)
from tests.engine.conftest import synthetic_stats_frame


def test_frobenius_identity_is_one() -> None:
    m = np.arange(9, dtype=np.float64).reshape(3, 3)
    assert frobenius_similarity(m, m) == pytest.approx(1.0)


def test_frobenius_symmetry() -> None:
    rng = np.random.default_rng(42)
    a = rng.standard_normal((4, 4))
    b = rng.standard_normal((4, 4))
    assert frobenius_similarity(a, b) == pytest.approx(frobenius_similarity(b, a))


def test_frobenius_range() -> None:
    rng = np.random.default_rng(0)
    for _ in range(50):
        a = rng.standard_normal((3, 3))
        b = rng.standard_normal((3, 3))
        s = frobenius_similarity(a, b)
        assert 0.0 < s <= 1.0


def test_frobenius_shape_mismatch_raises() -> None:
    a = np.zeros((2, 2))
    b = np.zeros((3, 3))
    with pytest.raises(ValueError, match="shape mismatch"):
        frobenius_similarity(a, b)


def test_frobenius_hand_computed() -> None:
    """``1 / (1 + sqrt(4)) = 1/3`` for two 2x2 matrices differing by 2 on each entry."""
    a = np.zeros((2, 2))
    b = np.ones((2, 2))
    # ||a - b||_F = sqrt(4) = 2
    assert frobenius_similarity(a, b) == pytest.approx(1.0 / 3.0)


def test_build_similarity_matrix_symmetry_and_diagonal() -> None:
    stats = synthetic_stats_frame()
    assignment = cluster_teams(
        stats,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=date(2099, 1, 1),
    )
    merged = merge_opponent_clusters(assignment)
    sim = build_similarity_matrix(merged)
    assert sim.n > 0
    assert sim.matrix.shape == (sim.n, sim.n)
    np.testing.assert_allclose(sim.matrix, sim.matrix.T, atol=1e-12)
    np.testing.assert_allclose(np.diag(sim.matrix), np.ones(sim.n), atol=1e-12)
    assert np.all(sim.matrix >= 0.0)
    assert np.all(sim.matrix <= 1.0 + 1e-12)


def test_similarity_threshold_is_within_data_range() -> None:
    stats = synthetic_stats_frame()
    assignment = cluster_teams(
        stats,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=date(2099, 1, 1),
    )
    merged = merge_opponent_clusters(assignment)
    sim = build_similarity_matrix(merged)
    tau = similarity_threshold(sim, 0.5)
    assert sim.matrix.min() - 1e-9 <= tau <= sim.matrix.max() + 1e-9


def test_find_similar_team_seasons_excludes_self() -> None:
    stats = synthetic_stats_frame()
    assignment = cluster_teams(
        stats,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=date(2099, 1, 1),
    )
    merged = merge_opponent_clusters(assignment)
    sim = build_similarity_matrix(merged)
    if sim.is_empty:
        pytest.skip("not enough data to form similarity matrix")
    team, season = sim.keys[0]
    similar = find_similar_team_seasons(sim, team=team, season=season, threshold=-1.0)
    assert (team, season) not in similar


def test_empty_matrix_helpers() -> None:
    empty = SimilarityMatrix(keys=[], matrix=np.zeros((0, 0)), index={})
    assert similarity_threshold(empty, 0.5) == 0.0
    assert find_similar_team_seasons(empty, team="x", season="y", threshold=0.0) == set()
    frame = empty.as_frame()
    assert frame.is_empty()
