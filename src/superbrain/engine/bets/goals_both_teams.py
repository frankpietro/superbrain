"""Both teams to score (BTTS / GG-NG)."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from superbrain.core.markets import Market
from superbrain.core.models import OddsSnapshot
from superbrain.engine.bets._helpers import paired_arrays
from superbrain.engine.bets.base import Outcome
from superbrain.engine.bets.registry import register

_YES = {"YES", "GG"}
_NO = {"NO", "NG"}


@register(Market.GOALS_BOTH_TEAMS)
class GoalsBothTeamsBet:
    market = Market.GOALS_BOTH_TEAMS

    def target_stat_columns(self, outcome: Outcome) -> list[str]:
        return ["goals"]

    def iter_outcomes(self, odds: Iterable[OddsSnapshot]) -> Iterable[Outcome]:
        seen: set[str] = set()
        for o in odds:
            if o.market != Market.GOALS_BOTH_TEAMS:
                continue
            canonical = _canonicalize(o.selection)
            if canonical is None or canonical in seen:
                continue
            seen.add(canonical)
            yield Outcome(market=self.market, selection=canonical, params={}, label=canonical)

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
        both = (a > 0) & (b > 0)
        if outcome.selection == "YES":
            return float(np.mean(both))
        return float(np.mean(~both))

    def validate_result(
        self,
        outcome: Outcome,
        *,
        home_value: float | None,
        away_value: float | None,
    ) -> bool | None:
        if home_value is None or away_value is None:
            return None
        both = home_value > 0 and away_value > 0
        if outcome.selection == "YES":
            return both
        return not both


def _canonicalize(selection: str) -> str | None:
    s = selection.upper()
    if s in _YES:
        return "YES"
    if s in _NO:
        return "NO"
    return None
