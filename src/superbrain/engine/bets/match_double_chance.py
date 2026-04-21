"""Match — double chance (1X / 12 / X2)."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from superbrain.core.markets import Market
from superbrain.core.models import OddsSnapshot
from superbrain.engine.bets._helpers import paired_arrays
from superbrain.engine.bets.base import Outcome
from superbrain.engine.bets.registry import register

_VALID = {"1X", "12", "X2"}


@register(Market.MATCH_DOUBLE_CHANCE)
class MatchDoubleChanceBet:
    market = Market.MATCH_DOUBLE_CHANCE

    def target_stat_columns(self, outcome: Outcome) -> list[str]:
        return ["goals"]

    def iter_outcomes(self, odds: Iterable[OddsSnapshot]) -> Iterable[Outcome]:
        seen: set[str] = set()
        for o in odds:
            if o.market != Market.MATCH_DOUBLE_CHANCE or o.selection not in _VALID:
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
        home = a > b
        draw = a == b
        away = a < b
        if outcome.selection == "1X":
            return float(np.mean(home | draw))
        if outcome.selection == "12":
            return float(np.mean(home | away))
        return float(np.mean(draw | away))

    def validate_result(
        self,
        outcome: Outcome,
        *,
        home_value: float | None,
        away_value: float | None,
    ) -> bool | None:
        if home_value is None or away_value is None:
            return None
        home = home_value > away_value
        draw = home_value == away_value
        away = home_value < away_value
        if outcome.selection == "1X":
            return home or draw
        if outcome.selection == "12":
            return home or away
        return draw or away
