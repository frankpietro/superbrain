"""Agglomerative clustering on team-match playing-style vectors.

Port of ``fbref24/refactored_src/engine/clustering.py``. Behaviour is
preserved bit-for-bit against the old implementation:

* ``StandardScaler`` (mean 0, std 1) on the stat columns.
* ``sklearn.cluster.AgglomerativeClustering`` with ``metric="cosine"``
  and ``linkage="average"``.
* Per-row integer cluster labels joined back onto the input frame.
* Opponent-cluster merge (for every row, add the cluster label of the
  opposing team in the same match).

The input is a :class:`polars.DataFrame` with one row per team-match and
a dedicated ``opponent`` column (derived by :func:`prepare_team_match_stats`
from the lake's :class:`~superbrain.core.models.TeamMatchStats` table,
which stores only ``team`` + ``is_home`` per row).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Final

import numpy as np
import polars as pl
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

CLUSTER_COL: Final = "cluster"
OPPONENT_CLUSTER_COL: Final = "cluster_opponent"
OPPONENT_COL: Final = "opponent"


@dataclass(frozen=True)
class ClusterAssignment:
    """Immutable result of ``cluster_teams``.

    :ivar data: the input frame with ``cluster`` and (if merged)
        ``cluster_opponent`` columns appended.
    :ivar n_clusters: number of clusters requested.
    :ivar columns_used: the stat columns actually fed into the clusterer
        (intersection of ``columns_of_interest`` and frame columns).
    :ivar training_cutoff: only rows with ``match_date < training_cutoff``
        were used.
    :ivar team_to_cluster: per-team aggregate label (majority vote across
        the team's rows in ``data``).
    :ivar cluster_to_teams: inverse mapping.
    """

    data: pl.DataFrame
    n_clusters: int
    columns_used: list[str]
    training_cutoff: date
    team_to_cluster: dict[str, int] = field(default_factory=dict)
    cluster_to_teams: dict[int, list[str]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return self.data.is_empty() or CLUSTER_COL not in self.data.columns


def prepare_team_match_stats(
    stats: pl.DataFrame,
    *,
    matches: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Join sibling rows to add an ``opponent`` column.

    The lake stores one row per ``(match_id, team)``, so the opponent of a
    row is the *other* row with the same ``match_id``. If a ``matches``
    frame is provided (preferred), use its ``(home_team, away_team)``
    columns — this preserves orientation for tests that rely on it.

    :param stats: ``team_match_stats`` frame
    :param matches: optional ``matches`` frame to resolve opponents
    :return: frame with an ``opponent`` column (same width as ``stats``
        plus one column)
    """
    if stats.is_empty():
        return stats.with_columns(pl.lit(None, dtype=pl.String).alias(OPPONENT_COL))

    if matches is not None and not matches.is_empty():
        m = matches.select(["match_id", "home_team", "away_team"])
        joined = stats.join(m, on="match_id", how="left")
        opponent = (
            pl.when(pl.col("team") == pl.col("home_team"))
            .then(pl.col("away_team"))
            .otherwise(pl.col("home_team"))
            .alias(OPPONENT_COL)
        )
        return joined.with_columns(opponent).drop(["home_team", "away_team"])

    sibling = stats.select(["match_id", "team"]).rename({"team": OPPONENT_COL})
    grouped = sibling.group_by("match_id").agg(pl.col(OPPONENT_COL))
    joined = stats.join(grouped, on="match_id", how="left")
    opponent_lists = joined.get_column(OPPONENT_COL).to_list()
    teams = joined.get_column("team").to_list()
    resolved: list[str | None] = []
    for opp_list, team in zip(opponent_lists, teams, strict=True):
        if opp_list is None:
            resolved.append(None)
            continue
        others = [o for o in opp_list if o != team]
        resolved.append(others[0] if others else None)
    return joined.with_columns(pl.Series(OPPONENT_COL, resolved, dtype=pl.String))


def cluster_teams(
    stats_df: pl.DataFrame,
    *,
    n_clusters: int,
    columns_of_interest: list[str],
    training_cutoff: date,
    random_state: int | None = 0,
) -> ClusterAssignment:
    """Cluster team-match rows by the chosen stat columns.

    Behaviour (preserved from the old implementation):

    * Rows with ``match_date >= training_cutoff`` are dropped — clustering
      only sees the past, preventing leakage.
    * Every ``columns_of_interest`` value present in the frame is fed to
      :class:`~sklearn.preprocessing.StandardScaler` (mean 0, std 1).
    * The scaled matrix is fed to
      :class:`~sklearn.cluster.AgglomerativeClustering` with
      ``metric="cosine"`` and ``linkage="average"``.
    * Rows with NaNs or nulls in any selected column are imputed to 0
      *after* scaling (reproduces the old pandas behaviour, which silently
      filled with zeros on ``.values``).

    :param stats_df: team-match frame with a ``match_date`` column
    :param n_clusters: target number of clusters (``sklearn`` parameter)
    :param columns_of_interest: stat columns to feed into the clusterer
    :param training_cutoff: only rows strictly before this date are used
    :param random_state: reserved for future deterministic tie-breaking;
        sklearn's agglomerative clustering ignores it, but we accept it
        for API stability.
    :return: a :class:`ClusterAssignment` with ``cluster`` joined on
    """
    del random_state

    logger.info(
        "clustering: n_clusters=%d cutoff=%s columns=%d",
        n_clusters,
        training_cutoff,
        len(columns_of_interest),
    )

    if "match_date" in stats_df.columns:
        training = stats_df.filter(pl.col("match_date") < training_cutoff)
    else:
        training = stats_df

    available = [c for c in columns_of_interest if c in training.columns]
    if training.is_empty() or not available:
        return ClusterAssignment(
            data=training.with_columns(pl.lit(None, dtype=pl.Int64).alias(CLUSTER_COL)),
            n_clusters=n_clusters,
            columns_used=available,
            training_cutoff=training_cutoff,
        )

    arr = training.select(available).fill_null(0.0).fill_nan(0.0).to_numpy().astype(np.float64)

    scaler = StandardScaler()
    scaled = scaler.fit_transform(arr)
    scaled = np.nan_to_num(scaled, nan=0.0, posinf=0.0, neginf=0.0)

    hc = AgglomerativeClustering(n_clusters=n_clusters, metric="cosine", linkage="average")
    labels = hc.fit_predict(scaled).astype(np.int64)

    with_labels = training.with_columns(pl.Series(CLUSTER_COL, labels))
    team_to_cluster = _majority_cluster_per_team(with_labels)
    cluster_to_teams: dict[int, list[str]] = {}
    for team, cluster in team_to_cluster.items():
        cluster_to_teams.setdefault(cluster, []).append(team)

    distribution = {
        int(k): int(v) for k, v in zip(*np.unique(labels, return_counts=True), strict=False)
    }
    logger.info("cluster distribution: %s", distribution)

    return ClusterAssignment(
        data=with_labels,
        n_clusters=n_clusters,
        columns_used=available,
        training_cutoff=training_cutoff,
        team_to_cluster=team_to_cluster,
        cluster_to_teams=cluster_to_teams,
    )


def merge_opponent_clusters(assignment: ClusterAssignment) -> ClusterAssignment:
    """Add the ``cluster_opponent`` column by self-joining on match-id.

    The old implementation merged on ``(date, season, team) ↔
    (date, season, opponent)``. Here we use ``(match_id, opponent) ↔
    (match_id, team)`` which is equivalent because ``match_id`` already
    fixes date + season and every match has exactly two teams — and it's
    vastly cheaper.

    :param assignment: output of :func:`cluster_teams`
    :return: the same assignment with ``cluster_opponent`` column added
    """
    df = assignment.data
    if df.is_empty() or CLUSTER_COL not in df.columns:
        return assignment
    if OPPONENT_COL not in df.columns:
        raise ValueError(
            "merge_opponent_clusters: frame missing 'opponent' column — "
            "call prepare_team_match_stats first"
        )

    pairs = df.select(["match_id", "team", CLUSTER_COL]).rename(
        {"team": OPPONENT_COL, CLUSTER_COL: OPPONENT_CLUSTER_COL}
    )
    merged = df.join(pairs, on=["match_id", OPPONENT_COL], how="left")
    return ClusterAssignment(
        data=merged,
        n_clusters=assignment.n_clusters,
        columns_used=assignment.columns_used,
        training_cutoff=assignment.training_cutoff,
        team_to_cluster=assignment.team_to_cluster,
        cluster_to_teams=assignment.cluster_to_teams,
    )


def _majority_cluster_per_team(frame: pl.DataFrame) -> dict[str, int]:
    if frame.is_empty() or CLUSTER_COL not in frame.columns:
        return {}
    counts = (
        frame.group_by(["team", CLUSTER_COL])
        .agg(pl.len().alias("n"))
        .sort(["team", "n", CLUSTER_COL], descending=[False, True, False])
    )
    first = counts.group_by("team", maintain_order=True).agg(
        pl.col(CLUSTER_COL).first().alias("majority")
    )
    return {row["team"]: int(row["majority"]) for row in first.to_dicts()}
