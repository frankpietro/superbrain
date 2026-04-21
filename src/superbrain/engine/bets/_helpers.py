"""Private helpers shared across concrete bet strategies."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np

from superbrain.core.models import OddsSnapshot


def paired_arrays(
    values_home: list[float], values_away: list[float]
) -> tuple[np.ndarray, np.ndarray]:
    """Truncate to the shorter list and return numpy arrays.

    The old bet code paired ``team1_values[i]`` with ``team2_values[i]``
    up to ``min(len(t1), len(t2))``. This helper preserves that.
    """
    n = min(len(values_home), len(values_away))
    if n == 0:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
    a = np.asarray(values_home[:n], dtype=np.float64)
    b = np.asarray(values_away[:n], dtype=np.float64)
    return a, b


def unique_outcomes_by_key[T](outcomes: Iterable[T], key: Any) -> list[T]:  # pragma: no cover
    """Stable dedupe helper — retained for future strategies."""
    seen: set[Any] = set()
    out: list[T] = []
    for o in outcomes:
        k = key(o)
        if k in seen:
            continue
        seen.add(k)
        out.append(o)
    return out


def get_threshold(odds: OddsSnapshot, *names: str) -> float | None:
    """Return the first numeric threshold field present in ``market_params``."""
    for name in names:
        if name in odds.market_params:
            try:
                return float(odds.market_params[name])
            except (TypeError, ValueError):
                return None
    return None
