"""Corners — single-team over/under."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from superbrain.core.markets import Market
from superbrain.core.models import OddsSnapshot
from superbrain.engine.bets._helpers import get_threshold
from superbrain.engine.bets.base import Outcome
from superbrain.engine.bets.registry import register


@register(Market.CORNER_TEAM)
class CornerTeamBet:
    market = Market.CORNER_TEAM

    def target_stat_columns(self, outcome: Outcome) -> list[str]:
        return ["corners"]

    def iter_outcomes(self, odds: Iterable[OddsSnapshot]) -> Iterable[Outcome]:
        seen: set[tuple[str, int, float]] = set()
        for o in odds:
            if o.market != Market.CORNER_TEAM:
                continue
            if o.selection not in ("OVER", "UNDER"):
                continue
            threshold = get_threshold(o, "threshold")
            team = o.market_params.get("team")
            try:
                team_num = int(team) if team is not None else None
            except (TypeError, ValueError):
                team_num = None
            if threshold is None or team_num not in (1, 2):
                continue
            assert team_num is not None
            key = (o.selection, team_num, threshold)
            if key in seen:
                continue
            seen.add(key)
            yield Outcome(
                market=self.market,
                selection=o.selection,
                params={"team": team_num, "threshold": threshold},
                label=f"T{team_num} {o.selection} {threshold:g}",
            )

    def compute_probability(
        self,
        outcome: Outcome,
        *,
        values_home: list[float],
        values_away: list[float],
    ) -> float:
        team = int(outcome.params["team"])
        values = values_home if team == 1 else values_away
        if not values:
            return 0.0
        arr = np.asarray(values, dtype=np.float64)
        threshold = float(outcome.params["threshold"])
        if outcome.selection == "OVER":
            return float(np.mean(arr >= threshold))
        return float(np.mean(arr < threshold))

    def validate_result(
        self,
        outcome: Outcome,
        *,
        home_value: float | None,
        away_value: float | None,
    ) -> bool | None:
        team = int(outcome.params["team"])
        value = home_value if team == 1 else away_value
        if value is None:
            return None
        threshold = float(outcome.params["threshold"])
        if outcome.selection == "OVER":
            return value >= threshold
        return value < threshold
