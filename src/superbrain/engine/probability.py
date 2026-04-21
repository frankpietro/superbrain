"""Empirical probability estimator via cluster-similarity neighbor pooling.

Port of ``fbref24/refactored_src/engine/probability.py``.

The algorithm, given a fixture ``(home, away, season)`` and a target stat
``s``:

1. Compute similarity threshold ``τ = quantile(similarity_matrix, q)``
   (old default ``q = 0.7``).
2. Let ``N_home = { (t, s') : sim[(home, season), (t, s')] > τ } - {(home, season)}``.
   Likewise ``N_away``.
3. For every season ``s'`` that appears in both ``N_home`` and ``N_away``,
   collect historical ``s`` values from matches where a team in
   ``N_home[s']`` played a team in ``N_away[s']`` (i.e. the row's
   ``(team, opponent, season) ∈ N_home x N_away x {s'}`` in the stats
   frame).
4. Return the two lists ``(values_home, values_away)`` — the home-team
   perspective and the away-team perspective. A concrete bet (over/under,
   BTTS, 1X2, …) then computes its probability from those two lists by
   element-wise pairing (indices modulo ``min(len1, len2)``, matching the
   old bet.calculate_probability semantics).

The pooling is floor-gated by ``min_matches``: if either list has fewer
than ``min_matches`` entries, both are returned empty and the caller
treats that as "not enough history".
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Final

import numpy as np
import polars as pl

from superbrain.engine.clustering import OPPONENT_COL
from superbrain.engine.similarity import (
    SimilarityMatrix,
    find_similar_team_seasons,
    similarity_threshold,
)

logger = logging.getLogger(__name__)


DEFAULT_QUANTILE: Final = 0.7
DEFAULT_MIN_MATCHES: Final = 6


@dataclass(frozen=True)
class ProbabilityConfig:
    """Tuning knobs for the neighbor-pooling estimator.

    :ivar quantile: global similarity quantile used as the neighbor cutoff.
        Matches the old ``AnalysisConfig.quantile`` default.
    :ivar min_matches: minimum sample size per side; below this the
        estimator returns empty lists (treated as "insufficient evidence"
        by the bet layer).
    """

    quantile: float = DEFAULT_QUANTILE
    min_matches: int = DEFAULT_MIN_MATCHES


class TargetStatIndex:
    """Pre-indexed lookup of historical target values by ``(team, opponent, season)``.

    Building this once per pricing call and re-using it across every bet
    outcome is the key optimization the old implementation made.

    :param stats_df: team-match stats frame (with ``opponent`` column
        attached by :func:`~superbrain.engine.clustering.prepare_team_match_stats`)
    :param target_column: stat column to extract (e.g. ``"corners"``,
        ``"goals"``, ``"yellow_cards"``)
    """

    __slots__ = ("_by_team_opp_season", "_target_col")

    def __init__(self, stats_df: pl.DataFrame, target_column: str) -> None:
        self._target_col = target_column
        self._by_team_opp_season: dict[tuple[str, str, str], np.ndarray] = {}

        if stats_df.is_empty() or target_column not in stats_df.columns:
            return
        if OPPONENT_COL not in stats_df.columns or "team" not in stats_df.columns:
            return
        if "season" not in stats_df.columns:
            return

        relevant = stats_df.select(
            [
                pl.col("team").cast(pl.String),
                pl.col(OPPONENT_COL).cast(pl.String),
                pl.col("season").cast(pl.String),
                pl.col(target_column).cast(pl.Float64),
            ]
        ).drop_nulls([target_column, OPPONENT_COL])

        team_arr = relevant.get_column("team").to_list()
        opp_arr = relevant.get_column(OPPONENT_COL).to_list()
        season_arr = relevant.get_column("season").to_list()
        target_arr = relevant.get_column(target_column).to_numpy().astype(np.float64)

        buckets: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for team, opp, season, value in zip(team_arr, opp_arr, season_arr, target_arr, strict=True):
            if team is None or opp is None or season is None:
                continue
            buckets[(team, opp, season)].append(float(value))

        self._by_team_opp_season = {k: np.asarray(v, dtype=np.float64) for k, v in buckets.items()}

    @property
    def target_column(self) -> str:
        return self._target_col

    def get_values(
        self, team_names: list[str], opponent_names: list[str], season: str
    ) -> list[float]:
        """Accumulate every target value for ``(team, opponent, season)`` triples."""
        result: list[float] = []
        for team in team_names:
            for opp in opponent_names:
                arr = self._by_team_opp_season.get((team, opp, season))
                if arr is not None:
                    result.extend(arr.tolist())
        return result


def collect_neighbor_values(
    *,
    sim: SimilarityMatrix,
    target_index: TargetStatIndex,
    home_team: str,
    away_team: str,
    season: str,
    config: ProbabilityConfig | None = None,
    threshold: float | None = None,
) -> tuple[list[float], list[float]]:
    """Gather the ``(values_home, values_away)`` sample for a fixture.

    :param sim: similarity matrix produced by :func:`build_similarity_matrix`
    :param target_index: pre-indexed target-stat lookup
    :param home_team: canonical home-team name
    :param away_team: canonical away-team name
    :param season: season code (same format as similarity-matrix keys)
    :param config: neighbor quantile + minimum sample-size gate
    :param threshold: optional precomputed threshold (otherwise derived
        from ``config.quantile``)
    :return: two parallel lists of historical values; empty when either
        side falls under ``config.min_matches``
    """
    if config is None:
        config = ProbabilityConfig()
    if sim.is_empty:
        return [], []

    tau = threshold if threshold is not None else similarity_threshold(sim, config.quantile)
    neighbors_home = find_similar_team_seasons(sim, team=home_team, season=season, threshold=tau)
    neighbors_away = find_similar_team_seasons(sim, team=away_team, season=season, threshold=tau)
    if not neighbors_home or not neighbors_away:
        return [], []

    by_season_home: dict[str, list[str]] = defaultdict(list)
    for team, s in neighbors_home:
        by_season_home[s].append(team)
    by_season_away: dict[str, list[str]] = defaultdict(list)
    for team, s in neighbors_away:
        by_season_away[s].append(team)
    common_seasons = set(by_season_home) & set(by_season_away)
    if not common_seasons:
        return [], []

    values_home: list[float] = []
    values_away: list[float] = []
    for s in common_seasons:
        home_like = by_season_home[s]
        away_like = by_season_away[s]
        values_home.extend(target_index.get_values(home_like, away_like, s))
        values_away.extend(target_index.get_values(away_like, home_like, s))

    if len(values_home) < config.min_matches or len(values_away) < config.min_matches:
        return [], []

    return values_home, values_away
