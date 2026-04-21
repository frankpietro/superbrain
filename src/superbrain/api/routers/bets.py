"""Bets router — engine surface.

TODO: wire engine. Phase 4a lands the value-bet engine; once available, this
router will compute edges against the current odds snapshot. Until then
``GET /bets/value`` returns an empty items page with a clear note and
``GET /bets/markets`` exposes the :mod:`superbrain.core.markets` registry so
the SPA can render the dropdowns it needs today.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from superbrain.api.schemas import MarketInfo, Page
from superbrain.core.markets import MARKET_METADATA

router = APIRouter(prefix="/bets", tags=["bets"])

_ENGINE_NOT_WIRED = "engine not yet wired"


@router.get("/value")
async def list_value_bets(
    league: Annotated[str | None, Query()] = None,
    min_edge: Annotated[float, Query(ge=0.0)] = 0.0,
) -> dict[str, Any]:
    """Return a stub response until the value-bet engine is wired in phase 4a."""
    del league, min_edge
    return {
        "items": [],
        "count": 0,
        "next_cursor": None,
        "note": _ENGINE_NOT_WIRED,
    }


@router.get("/markets", response_model=Page[MarketInfo])
async def list_markets() -> Page[MarketInfo]:
    """Return every registered :class:`Market` with its metadata."""
    items: list[MarketInfo] = []
    for code, meta in sorted(MARKET_METADATA.items(), key=lambda kv: kv[0].value):
        items.append(
            MarketInfo(
                code=code.value,
                category=meta.category.value,
                human_name=meta.human_name,
                param_keys=list(meta.param_keys),
                selections=list(meta.selections),
                target_stat=meta.target_stat,
            )
        )
    return Page[MarketInfo](items=items, count=len(items), next_cursor=None)
