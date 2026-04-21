"""Bet-type registry.

Importing this package registers every concrete strategy via
:func:`superbrain.engine.bets.registry.register`. Downstream code should
import :data:`BET_REGISTRY` or call :func:`strategy_for` from the
registry module — never reach into these submodules directly.
"""

from __future__ import annotations

from superbrain.engine.bets import (
    cards_total,
    corner_1x2,
    corner_combo,
    corner_handicap,
    corner_team,
    corner_total,
    goals_both_teams,
    goals_over_under,
    goals_team,
    match_1x2,
    match_double_chance,
    shots_total,
)
from superbrain.engine.bets.base import BetStrategy, EngineContext, Outcome
from superbrain.engine.bets.registry import (
    BET_REGISTRY,
    register,
    registered_markets,
    strategy_for,
)

__all__ = [
    "BET_REGISTRY",
    "BetStrategy",
    "EngineContext",
    "Outcome",
    "register",
    "registered_markets",
    "strategy_for",
]
