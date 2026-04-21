"""Cards — total over/under (yellow cards only, matching the old semantics)."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from superbrain.core.markets import Market
from superbrain.core.models import OddsSnapshot
from superbrain.engine.bets._helpers import get_threshold, paired_arrays
from superbrain.engine.bets.base import Outcome
from superbrain.engine.bets.registry import register


@register(Market.CARDS_TOTAL)
class CardsTotalBet:
    market = Market.CARDS_TOTAL

    def target_stat_columns(self, outcome: Outcome) -> list[str]:
        return ["yellow_cards"]

    def iter_outcomes(self, odds: Iterable[OddsSnapshot]) -> Iterable[Outcome]:
        seen: set[tuple[str, float]] = set()
        for o in odds:
            if o.market != Market.CARDS_TOTAL:
                continue
            if o.selection not in ("OVER", "UNDER"):
                continue
            threshold = get_threshold(o, "threshold")
            if threshold is None:
                continue
            key = (o.selection, threshold)
            if key in seen:
                continue
            seen.add(key)
            yield Outcome(
                market=self.market,
                selection=o.selection,
                params={"threshold": threshold},
                label=f"{o.selection} {threshold:g}",
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
        total = a + b
        threshold = float(outcome.params["threshold"])
        if outcome.selection == "OVER":
            return float(np.mean(total >= threshold))
        return float(np.mean(total < threshold))

    def validate_result(
        self,
        outcome: Outcome,
        *,
        home_value: float | None,
        away_value: float | None,
    ) -> bool | None:
        if home_value is None or away_value is None:
            return None
        total = float(home_value) + float(away_value)
        threshold = float(outcome.params["threshold"])
        if outcome.selection == "OVER":
            return total >= threshold
        return total < threshold
