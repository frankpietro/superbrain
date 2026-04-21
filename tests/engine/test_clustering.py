"""Unit tests for ``superbrain.engine.clustering``."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from superbrain.engine.clustering import (
    CLUSTER_COL,
    OPPONENT_COL,
    cluster_teams,
    merge_opponent_clusters,
    prepare_team_match_stats,
)
from tests.engine.conftest import synthetic_stats_frame


def test_prepare_adds_opponent_column() -> None:
    stats = synthetic_stats_frame()
    stats_no_opp = stats.drop(OPPONENT_COL)
    prepared = prepare_team_match_stats(stats_no_opp)
    assert OPPONENT_COL in prepared.columns
    assert prepared.height == stats.height
    for row in prepared.iter_rows(named=True):
        assert row[OPPONENT_COL] is not None
        assert row[OPPONENT_COL] != row["team"]


def test_cluster_labels_are_deterministic() -> None:
    stats = synthetic_stats_frame()
    cutoff = date(2099, 1, 1)
    a = cluster_teams(
        stats,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=cutoff,
    )
    b = cluster_teams(
        stats,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=cutoff,
    )
    assert a.data.get_column(CLUSTER_COL).to_list() == b.data.get_column(CLUSTER_COL).to_list()


def test_cluster_count_matches_parameter() -> None:
    stats = synthetic_stats_frame()
    assignment = cluster_teams(
        stats,
        n_clusters=3,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=date(2099, 1, 1),
    )
    labels = assignment.data.get_column(CLUSTER_COL).to_list()
    assert len(set(labels)) <= 3
    assert len(set(labels)) >= 1
    assert all(0 <= label < 3 for label in labels)


def test_training_cutoff_excludes_future_rows() -> None:
    stats = synthetic_stats_frame()
    cutoff = date(2023, 9, 3)
    assignment = cluster_teams(
        stats,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=cutoff,
    )
    assert all(d < cutoff for d in assignment.data.get_column("match_date").to_list())


def test_merge_opponent_clusters_adds_column() -> None:
    stats = synthetic_stats_frame()
    assignment = cluster_teams(
        stats,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=date(2099, 1, 1),
    )
    merged = merge_opponent_clusters(assignment)
    assert "cluster_opponent" in merged.data.columns


def test_row_permutation_invariance() -> None:
    """Same clustering result regardless of row order in the input."""
    stats = synthetic_stats_frame()
    shuffled = (
        stats.with_columns(pl.int_range(pl.len()).shuffle(seed=42).alias("_perm"))
        .sort("_perm")
        .drop("_perm")
    )
    base = cluster_teams(
        stats,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=date(2099, 1, 1),
    )
    shuf = cluster_teams(
        shuffled,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=date(2099, 1, 1),
    )
    base_map = {
        row["match_id"] + row["team"]: row[CLUSTER_COL] for row in base.data.iter_rows(named=True)
    }
    shuf_map = {
        row["match_id"] + row["team"]: row[CLUSTER_COL] for row in shuf.data.iter_rows(named=True)
    }
    assert _labels_equivalent_up_to_permutation(base_map, shuf_map)


def _labels_equivalent_up_to_permutation(a: dict[str, int], b: dict[str, int]) -> bool:
    """Two label maps are equivalent up to cluster-ID permutation iff they
    induce the same partition of rows."""
    if set(a.keys()) != set(b.keys()):
        return False
    grouping_a: dict[int, set[str]] = {}
    for key, label in a.items():
        grouping_a.setdefault(label, set()).add(key)
    grouping_b: dict[int, set[str]] = {}
    for key, label in b.items():
        grouping_b.setdefault(label, set()).add(key)
    frozen_a = {frozenset(s) for s in grouping_a.values()}
    frozen_b = {frozenset(s) for s in grouping_b.values()}
    return frozen_a == frozen_b


def test_empty_input_is_safe() -> None:
    empty = pl.DataFrame(
        schema={
            "match_id": pl.String,
            "team": pl.String,
            "opponent": pl.String,
            "season": pl.String,
            "match_date": pl.Date,
            "goals": pl.Int64,
            "corners": pl.Int64,
        }
    )
    assignment = cluster_teams(
        empty,
        n_clusters=3,
        columns_of_interest=["goals", "corners"],
        training_cutoff=date(2099, 1, 1),
    )
    assert assignment.is_empty


def test_merge_opponent_clusters_requires_opponent_column() -> None:
    stats = synthetic_stats_frame().drop(OPPONENT_COL)
    assignment = cluster_teams(
        stats,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=date(2099, 1, 1),
    )
    with pytest.raises(ValueError, match="opponent"):
        merge_opponent_clusters(assignment)
