"""Corners — per-team combo over/under."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from superbrain.core.markets import Market
from superbrain.core.models import OddsSnapshot
from superbrain.engine.bets._helpers import get_threshold
from superbrain.engine.bets.base import Outcome
from superbrain.engine.bets.registry import register

_VALID_SELECTIONS = ("OVER+OVER", "OVER+UNDER", "UNDER+OVER", "UNDER+UNDER")


@register(Market.CORNER_COMBO)
class CornerComboBet:
    market = Market.CORNER_COMBO

    def target_stat_columns(self, outcome: Outcome) -> list[str]:
        return ["corners"]

    def iter_outcomes(self, odds: Iterable[OddsSnapshot]) -> Iterable[Outcome]:
        seen: set[tuple[str, float, float]] = set()
        for o in odds:
            if o.market != Market.CORNER_COMBO:
                continue
            if o.selection not in _VALID_SELECTIONS:
                continue
            t1 = get_threshold(o, "threshold_1", "threshold_team1")
            t2 = get_threshold(o, "threshold_2", "threshold_team2")
            if t1 is None or t2 is None:
                continue
            key = (o.selection, t1, t2)
            if key in seen:
                continue
            seen.add(key)
            yield Outcome(
                market=self.market,
                selection=o.selection,
                params={"threshold_1": t1, "threshold_2": t2},
                label=f"{o.selection} ({t1:g}/{t2:g})",
            )

    def compute_probability(
        self,
        outcome: Outcome,
        *,
        values_home: list[float],
        values_away: list[float],
    ) -> float:
        if not values_home or not values_away:
            return 0.0
        a = np.asarray(values_home, dtype=np.float64)
        b = np.asarray(values_away, dtype=np.float64)
        t1 = float(outcome.params["threshold_1"])
        t2 = float(outcome.params["threshold_2"])
        u1 = float(np.mean(a < t1))
        o1 = float(np.mean(a >= t1))
        u2 = float(np.mean(b < t2))
        o2 = float(np.mean(b >= t2))
        table = {
            "UNDER+UNDER": u1 * u2,
            "UNDER+OVER": u1 * o2,
            "OVER+UNDER": o1 * u2,
            "OVER+OVER": o1 * o2,
        }
        return table[outcome.selection]

    def validate_result(
        self,
        outcome: Outcome,
        *,
        home_value: float | None,
        away_value: float | None,
    ) -> bool | None:
        if home_value is None or away_value is None:
            return None
        t1 = float(outcome.params["threshold_1"])
        t2 = float(outcome.params["threshold_2"])
        u1 = home_value < t1
        o1 = home_value >= t1
        u2 = away_value < t2
        o2 = away_value >= t2
        table = {
            "UNDER+UNDER": u1 and u2,
            "UNDER+OVER": u1 and o2,
            "OVER+UNDER": o1 and u2,
            "OVER+OVER": o1 and o2,
        }
        return bool(table[outcome.selection])
