"""Corners — handicap."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from superbrain.core.markets import Market
from superbrain.core.models import OddsSnapshot
from superbrain.engine.bets._helpers import get_threshold, paired_arrays
from superbrain.engine.bets.base import Outcome
from superbrain.engine.bets.registry import register


@register(Market.CORNER_HANDICAP)
class CornerHandicapBet:
    market = Market.CORNER_HANDICAP

    def target_stat_columns(self, outcome: Outcome) -> list[str]:
        return ["corners"]

    def iter_outcomes(self, odds: Iterable[OddsSnapshot]) -> Iterable[Outcome]:
        seen: set[tuple[str, float]] = set()
        for o in odds:
            if o.market != Market.CORNER_HANDICAP:
                continue
            if o.selection not in ("HOME", "AWAY"):
                continue
            handicap = get_threshold(o, "handicap")
            if handicap is None:
                continue
            key = (o.selection, handicap)
            if key in seen:
                continue
            seen.add(key)
            yield Outcome(
                market=self.market,
                selection=o.selection,
                params={"handicap": handicap},
                label=f"{o.selection} {handicap:+g}",
            )

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
        handicap = float(outcome.params["handicap"])
        if outcome.selection == "HOME":
            return float(np.mean((a + handicap) > b))
        return float(np.mean((b + handicap) > a))

    def validate_result(
        self,
        outcome: Outcome,
        *,
        home_value: float | None,
        away_value: float | None,
    ) -> bool | None:
        if home_value is None or away_value is None:
            return None
        handicap = float(outcome.params["handicap"])
        if outcome.selection == "HOME":
            return (home_value + handicap) > away_value
        return (away_value + handicap) > home_value
