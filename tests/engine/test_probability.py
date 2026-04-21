"""Unit tests for ``superbrain.engine.probability``."""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from superbrain.engine.clustering import (
    cluster_teams,
    merge_opponent_clusters,
)
from superbrain.engine.probability import (
    ProbabilityConfig,
    TargetStatIndex,
    collect_neighbor_values,
)
from superbrain.engine.similarity import build_similarity_matrix
from tests.engine.conftest import synthetic_stats_frame


def test_target_stat_index_roundtrip() -> None:
    stats = synthetic_stats_frame()
    idx = TargetStatIndex(stats, "goals")
    values = idx.get_values(["A"], ["B"], "2023-24")
    expected = (
        stats.filter(
            (pl.col("team") == "A") & (pl.col("opponent") == "B") & (pl.col("season") == "2023-24")
        )
        .get_column("goals")
        .cast(pl.Float64)
        .to_list()
    )
    assert sorted(values) == sorted(expected)


def test_target_stat_index_missing_returns_empty() -> None:
    stats = synthetic_stats_frame()
    idx = TargetStatIndex(stats, "goals")
    assert idx.get_values(["Missing"], ["A"], "2023-24") == []


def test_target_stat_index_handles_missing_column() -> None:
    stats = synthetic_stats_frame().drop("goals")
    idx = TargetStatIndex(stats, "goals")
    assert idx.get_values(["A"], ["B"], "2023-24") == []


def test_collect_neighbor_values_returns_empty_when_below_min_matches() -> None:
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
        pytest.skip("no similarity matrix built")
    target = TargetStatIndex(stats, "goals")
    home, _ = sim.keys[0]
    away_key = next((k for k in sim.keys if k[0] != home), None)
    if away_key is None:
        pytest.skip("not enough teams")
    away = away_key[0]
    vh, va = collect_neighbor_values(
        sim=sim,
        target_index=target,
        home_team=home,
        away_team=away,
        season="2023-24",
        config=ProbabilityConfig(quantile=0.7, min_matches=10_000),
    )
    assert vh == []
    assert va == []


def test_collect_neighbor_values_hand_computed() -> None:
    """A toy 5-team history where we can verify the neighbor sample by inspection.

    We construct a stats frame where every team plays every other team
    twice in season ``2023-24``, with stable ``goals`` values. Because
    every team is statistically identical, every pair is a neighbor and
    the returned ``values_home`` is simply the list of goals scored by
    any team against any opponent.
    """
    rows = []
    teams = ["T1", "T2", "T3", "T4", "T5"]
    for day, home in enumerate(teams):
        for away in teams:
            if home == away:
                continue
            rows.append(
                {
                    "match_id": f"{home}-{away}-{day}",
                    "team": home,
                    "opponent": away,
                    "is_home": True,
                    "league": "serie_a",
                    "season": "2023-24",
                    "match_date": date(2023, 9, 1),
                    "goals": 2,
                    "corners": 6,
                    "shots": 11,
                    "shots_on_target": 4,
                    "yellow_cards": 2,
                    "fouls": 10,
                    "goals_conceded": 1,
                }
            )
            rows.append(
                {
                    "match_id": f"{home}-{away}-{day}",
                    "team": away,
                    "opponent": home,
                    "is_home": False,
                    "league": "serie_a",
                    "season": "2023-24",
                    "match_date": date(2023, 9, 1),
                    "goals": 1,
                    "corners": 4,
                    "shots": 9,
                    "shots_on_target": 3,
                    "yellow_cards": 3,
                    "fouls": 11,
                    "goals_conceded": 2,
                }
            )
    stats = pl.DataFrame(rows)
    assignment = cluster_teams(
        stats,
        n_clusters=2,
        columns_of_interest=["goals", "corners", "shots"],
        training_cutoff=date(2099, 1, 1),
    )
    merged = merge_opponent_clusters(assignment)
    sim = build_similarity_matrix(merged)
    target = TargetStatIndex(stats, "goals")
    vh, va = collect_neighbor_values(
        sim=sim,
        target_index=target,
        home_team="T1",
        away_team="T2",
        season="2023-24",
        config=ProbabilityConfig(quantile=0.0, min_matches=1),
        threshold=-1.0,
    )
    assert len(vh) > 0
    assert len(va) > 0
    arr_h = np.asarray(vh)
    arr_a = np.asarray(va)
    # goals are either 1 (away side) or 2 (home side) by construction
    assert set(np.unique(arr_h).tolist()).issubset({1.0, 2.0})
    assert set(np.unique(arr_a).tolist()).issubset({1.0, 2.0})
