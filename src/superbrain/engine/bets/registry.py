"""Market → strategy registry.

Every concrete :class:`~superbrain.engine.bets.base.BetStrategy` calls
:func:`register` exactly once at import time. Downstream code calls
:func:`strategy_for` to resolve a strategy given a market.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from superbrain.core.markets import Market
from superbrain.engine.bets.base import BetStrategy

BET_REGISTRY: dict[Market, BetStrategy] = {}

T = TypeVar("T", bound=BetStrategy)


def register(market: Market) -> Callable[[type[T]], type[T]]:
    """Class decorator that registers a :class:`BetStrategy` subclass.

    Usage::

        @register(Market.CORNER_TOTAL)
        class CornerTotalBet(BetStrategy):
            ...

    :param market: the market this strategy handles
    :return: the decorated class (unchanged)
    """

    def _decorate(cls: type[T]) -> type[T]:
        instance = cls()
        BET_REGISTRY[market] = instance
        return cls

    return _decorate


def strategy_for(market: Market) -> BetStrategy:
    """Return the registered strategy for ``market``.

    :param market: market code (enum)
    :raises KeyError: if no strategy is registered
    """
    try:
        return BET_REGISTRY[market]
    except KeyError as exc:
        raise KeyError(
            f"no bet strategy registered for market {market!r}; "
            f"available: {sorted(m.value for m in BET_REGISTRY)}"
        ) from exc


def registered_markets() -> list[Market]:
    """Sorted list of markets that currently have a strategy."""
    return sorted(BET_REGISTRY.keys(), key=lambda m: m.value)


def _clear_registry_for_tests() -> None:
    """Test helper — drop every registration. Never call in production."""
    BET_REGISTRY.clear()
