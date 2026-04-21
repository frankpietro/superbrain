"""Bet-type abstraction — probability is a pure function of the sample.

Every concrete bet lives in its own module under
``superbrain.engine.bets`` and is registered through
:mod:`superbrain.engine.bets.registry`. The engine interacts with them
through three pieces:

* :class:`Outcome` — a pydantic model that carries enough information to
  (a) evaluate its probability from two lists of historical target values
  and (b) look up its own odds in an :class:`OddsSnapshot` feed.
* :class:`BetStrategy` — one per :class:`~superbrain.core.markets.Market`,
  maps odds rows into :class:`Outcome` instances, declares the stat
  column(s) it needs, and implements probability/validation.
* :class:`EngineContext` — the bundle that ``price_fixture`` passes down
  (historical matches, stats with opponent column, similarity matrix,
  cluster assignment, :class:`~superbrain.engine.probability.ProbabilityConfig`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from superbrain.core.markets import Market
from superbrain.core.models import OddsSnapshot
from superbrain.engine.clustering import ClusterAssignment
from superbrain.engine.probability import ProbabilityConfig, TargetStatIndex
from superbrain.engine.similarity import SimilarityMatrix


class Outcome(BaseModel):
    """One priceable selection within a market.

    :ivar market: the :class:`Market` code this outcome belongs to.
    :ivar selection: the canonical selection label (e.g. ``"OVER"``,
        ``"1"``, ``"YES"``).
    :ivar params: the stable market-parameter dict (e.g.
        ``{"threshold": 9.5}``); matches the shape of
        ``OddsSnapshot.market_params``.
    :ivar label: optional human-readable label for debugging / UI.
    """

    model_config = ConfigDict(frozen=True)

    market: Market
    selection: str
    params: dict[str, Any] = Field(default_factory=dict)
    label: str | None = None

    def matches_odds(self, odds: OddsSnapshot) -> bool:
        """Return ``True`` iff ``odds`` prices this exact outcome."""
        if odds.market != self.market:
            return False
        if odds.selection != self.selection:
            return False
        return _params_equivalent(self.params, odds.market_params)

    def key(self) -> tuple[str, str, str]:
        """Stable dedupe key: ``(market, selection, params_hash)``."""
        h = hashlib.sha1(json.dumps(self.params, sort_keys=True, default=str).encode()).hexdigest()[
            :12
        ]
        return (self.market.value, self.selection, h)


def _params_equivalent(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if set(a) != set(b):
        return False
    for k, av in a.items():
        bv = b[k]
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            if abs(float(av) - float(bv)) > 1e-9:
                return False
        elif str(av) != str(bv):
            return False
    return True


@dataclass(frozen=True)
class EngineContext:
    """Bundle of frozen state a pricing call reuses across many outcomes.

    :ivar stats_df: team-match stats with ``opponent`` column attached
        (the output of
        :func:`~superbrain.engine.clustering.prepare_team_match_stats`).
    :ivar similarity: similarity matrix over ``(team, season)`` keys.
    :ivar assignment: cluster assignment (kept for downstream introspection).
    :ivar config: probability-estimator knobs.
    :ivar target_indexes: cache of :class:`TargetStatIndex` per column —
        populated lazily by :meth:`target_index`.
    """

    stats_df: pl.DataFrame
    similarity: SimilarityMatrix
    assignment: ClusterAssignment
    config: ProbabilityConfig = field(default_factory=ProbabilityConfig)
    target_indexes: dict[str, TargetStatIndex] = field(default_factory=dict)

    def target_index(self, column: str) -> TargetStatIndex:
        cached = self.target_indexes.get(column)
        if cached is not None:
            return cached
        idx = TargetStatIndex(self.stats_df, column)
        self.target_indexes[column] = idx
        return idx


class BetStrategy(Protocol):
    """One bet type — the engine's sole interface to a market.

    A strategy is expected to be stateless: all state lives in
    :class:`EngineContext` and the :class:`Outcome` it emits.
    """

    market: Market

    def target_stat_columns(self, outcome: Outcome) -> list[str]:
        """Stat columns from ``TeamMatchStats`` needed to price ``outcome``."""
        ...

    def iter_outcomes(self, odds: Iterable[OddsSnapshot]) -> Iterable[Outcome]:
        """Materialize :class:`Outcome` objects from a group of odds rows.

        Implementations should dedupe equivalent outcomes (same market +
        selection + params) and may filter out malformed rows.
        """
        ...

    def compute_probability(
        self,
        outcome: Outcome,
        *,
        values_home: list[float],
        values_away: list[float],
    ) -> float:
        """Evaluate the model probability of ``outcome`` given the neighbor sample."""
        ...

    def validate_result(
        self,
        outcome: Outcome,
        *,
        home_value: float | None,
        away_value: float | None,
    ) -> bool | None:
        """Return whether ``outcome`` won for actual realized values.

        Returns ``None`` when either input is missing (insufficient
        data to decide the bet, e.g. a stat the scraper didn't capture).
        """
        ...
