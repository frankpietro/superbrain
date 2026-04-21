"""1X2 match result."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from superbrain.core.markets import Market
from superbrain.core.models import OddsSnapshot
from superbrain.engine.bets._helpers import paired_arrays
from superbrain.engine.bets.base import Outcome
from superbrain.engine.bets.registry import register

_VALID = {"1", "X", "2"}


@register(Market.MATCH_1X2)
class Match1x2Bet:
    market = Market.MATCH_1X2

    def target_stat_columns(self, outcome: Outcome) -> list[str]:
        return ["goals"]

    def iter_outcomes(self, odds: Iterable[OddsSnapshot]) -> Iterable[Outcome]:
        seen: set[str] = set()
        for o in odds:
            if o.market != Market.MATCH_1X2 or o.selection not in _VALID:
                continue
            if o.selection in seen:
                continue
            seen.add(o.selection)
            yield Outcome(market=self.market, selection=o.selection, params={}, label=o.selection)

    def compute_probability(
        self,
        outcome: Outcome,
        *,
        values_home: list[float],
        values_away: list[float],
    ) -> float:
        a, b = paired_arrays(values_home, values_away)
        if a.size == 0:
            return 0.0
        if outcome.selection == "1":
            return float(np.mean(a > b))
        if outcome.selection == "X":
            return float(np.mean(a == b))
        return float(np.mean(a < b))

    def validate_result(
        self,
        outcome: Outcome,
        *,
        home_value: float | None,
        away_value: float | None,
    ) -> bool | None:
        if home_value is None or away_value is None:
            return None
        if outcome.selection == "1":
            return home_value > away_value
        if outcome.selection == "X":
            return home_value == away_value
        return home_value < away_value
