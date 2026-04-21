"""Team-pair similarity from clustered match history.

Port of ``fbref24/refactored_src/engine/similarity.py``. For each
``(team, season)`` pair we build a ``n_clusters x n_clusters``
co-occurrence matrix from ``(cluster, opponent_cluster)`` pairs observed
in that team's matches, normalize it to a probability distribution, then
compute pairwise similarity as ``1 / (1 + ||A - B||_F)``.

The Frobenius norm of a ``k x k`` matrix equals the Euclidean norm of
its flat vectorization, so ``scipy.spatial.distance.pdist(..., "euclidean")``
computes the same quantity as the old Python loop — and does so in C.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np
import polars as pl
from scipy.spatial.distance import pdist, squareform

from superbrain.engine.clustering import (
    CLUSTER_COL,
    OPPONENT_CLUSTER_COL,
    ClusterAssignment,
)

logger = logging.getLogger(__name__)

TEAM_SEASON_SEPARATOR: Final = "|"


@dataclass(frozen=True)
class SimilarityMatrix:
    """Symmetric ``(team, season) x (team, season)`` similarity matrix.

    :ivar keys: ordered list of ``(team, season)`` tuples; row ``i`` of
        ``matrix`` corresponds to ``keys[i]``.
    :ivar matrix: ``n x n`` float64 symmetric array with 1.0 on the diagonal.
    :ivar index: lookup from ``(team, season)`` to row index.
    """

    keys: list[tuple[str, str]]
    matrix: np.ndarray
    index: dict[tuple[str, str], int]

    @property
    def n(self) -> int:
        return len(self.keys)

    @property
    def is_empty(self) -> bool:
        return self.n == 0

    def row(self, team: str, season: str) -> np.ndarray | None:
        idx = self.index.get((team, season))
        if idx is None:
            return None
        result: np.ndarray = self.matrix[idx]
        return result

    def as_frame(self) -> pl.DataFrame:
        """Return the similarity matrix as a long polars frame."""
        if self.is_empty:
            return pl.DataFrame(
                schema={
                    "team_a": pl.String,
                    "season_a": pl.String,
                    "team_b": pl.String,
                    "season_b": pl.String,
                    "similarity": pl.Float64,
                }
            )
        i_teams = [k[0] for k in self.keys]
        i_seasons = [k[1] for k in self.keys]
        rows: list[dict[str, object]] = []
        for i, (ta, sa) in enumerate(zip(i_teams, i_seasons, strict=True)):
            for j, (tb, sb) in enumerate(zip(i_teams, i_seasons, strict=True)):
                rows.append(
                    {
                        "team_a": ta,
                        "season_a": sa,
                        "team_b": tb,
                        "season_b": sb,
                        "similarity": float(self.matrix[i, j]),
                    }
                )
        return pl.DataFrame(rows)


def frobenius_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute ``1 / (1 + ||a - b||_F)``.

    :param a: first matrix
    :param b: second matrix of the same shape
    :return: similarity in ``(0, 1]``; exactly ``1`` iff ``a == b``
    """
    if a.shape != b.shape:
        raise ValueError(f"frobenius_similarity: shape mismatch {a.shape} vs {b.shape}")
    diff = a - b
    distance = float(np.sqrt(np.sum(diff * diff)))
    return 1.0 / (1.0 + distance)


def build_similarity_matrix(assignment: ClusterAssignment) -> SimilarityMatrix:
    """Build the ``(team, season)`` similarity matrix from clustered history.

    :param assignment: output of
        :func:`~superbrain.engine.clustering.merge_opponent_clusters`
    :return: :class:`SimilarityMatrix`
    """
    df = assignment.data
    if df.is_empty() or CLUSTER_COL not in df.columns or OPPONENT_CLUSTER_COL not in df.columns:
        logger.warning("similarity: empty or uncluster-merged frame; returning empty matrix")
        return SimilarityMatrix(keys=[], matrix=np.zeros((0, 0)), index={})

    max_cluster_raw = df.get_column(CLUSTER_COL).max()
    max_cluster = int(max_cluster_raw) if isinstance(max_cluster_raw, (int, float)) else 0
    n_clusters = max_cluster + 1
    flat_size = n_clusters * n_clusters

    relevant = df.select(
        [
            pl.col("team").cast(pl.String),
            pl.col("season").cast(pl.String),
            pl.col(CLUSTER_COL).cast(pl.Int64),
            pl.col(OPPONENT_CLUSTER_COL).cast(pl.Int64),
        ]
    ).drop_nulls([CLUSTER_COL, OPPONENT_CLUSTER_COL])

    if relevant.is_empty():
        return SimilarityMatrix(keys=[], matrix=np.zeros((0, 0)), index={})

    keys_series = (
        relevant.get_column("team") + TEAM_SEASON_SEPARATOR + relevant.get_column("season")
    )
    unique_keys = keys_series.unique(maintain_order=True).to_list()
    key_to_idx = {k: i for i, k in enumerate(unique_keys)}

    n_ts = len(unique_keys)
    counts = np.zeros((n_ts, flat_size), dtype=np.float64)

    ki = np.asarray([key_to_idx[k] for k in keys_series.to_list()], dtype=np.int64)
    clusters = relevant.get_column(CLUSTER_COL).to_numpy().astype(np.int64)
    opp_clusters = relevant.get_column(OPPONENT_CLUSTER_COL).to_numpy().astype(np.int64)
    flat_indices = clusters * n_clusters + opp_clusters

    np.add.at(counts, (ki, flat_indices), 1.0)

    row_sums = counts.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0.0] = 1.0
    normalized = counts / row_sums

    distances = pdist(normalized, metric="euclidean")
    similarities = 1.0 / (1.0 + distances)
    sim_square = squareform(similarities)
    np.fill_diagonal(sim_square, 1.0)

    keys: list[tuple[str, str]] = []
    for k in unique_keys:
        team, sep, season = k.rpartition(TEAM_SEASON_SEPARATOR)
        if not sep:
            team, season = k, ""
        keys.append((team, season))

    index = {k: i for i, k in enumerate(keys)}
    logger.info("similarity: %d x %d team-season matrix", n_ts, n_ts)
    return SimilarityMatrix(keys=keys, matrix=sim_square, index=index)


def similarity_threshold(sim: SimilarityMatrix, quantile: float) -> float:
    """Compute the quantile threshold over all similarity values.

    :param sim: similarity matrix
    :param quantile: quantile in ``[0, 1]`` (old default: 0.7)
    :return: threshold value (``0.0`` for an empty matrix)
    """
    if sim.is_empty:
        return 0.0
    return float(np.quantile(sim.matrix.ravel(), quantile))


def find_similar_team_seasons(
    sim: SimilarityMatrix,
    *,
    team: str,
    season: str,
    threshold: float,
) -> set[tuple[str, str]]:
    """Return every ``(team, season)`` pair with similarity strictly above ``threshold``.

    The self-entry ``(team, season)`` is excluded (its similarity is 1.0
    but it is the query itself).

    :param sim: similarity matrix
    :param team: query team
    :param season: query season (as a string, same format as the matrix keys)
    :param threshold: lower bound; matches must have ``sim > threshold``
    :return: set of ``(team, season)`` tuples (``set`` matches the old
        semantics — order-independent)
    """
    if sim.is_empty:
        return set()
    row = sim.row(team, season)
    if row is None:
        return set()
    mask = row > threshold
    return {sim.keys[j] for j, keep in enumerate(mask) if keep and sim.keys[j] != (team, season)}
