"""Bets router — value-bet detection over upcoming fixtures.

``GET /bets/value`` prices every upcoming fixture with the engine's default
:class:`~superbrain.engine.pipeline.PricingConfig`, drops rows whose edge
falls below ``min_edge``, and returns the survivors sorted by descending
edge. The computation runs in a threadpool because the engine is pure CPU
and we don't want to block the asyncio loop.

``GET /bets/markets`` exposes the :mod:`superbrain.core.markets` registry so
the SPA can populate its dropdowns from the source of truth.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Annotated, Any

import anyio
import polars as pl
from fastapi import APIRouter, Depends, Query

from superbrain.api.deps import get_lake
from superbrain.api.schemas import (
    MarketInfo,
    Page,
    ValueBetItem,
    ValueBetsResponse,
)
from superbrain.core.markets import MARKET_METADATA, Market
from superbrain.core.models import League, Match
from superbrain.data.connection import Lake
from superbrain.engine.pipeline import (
    DEFAULT_MIN_HISTORY_MATCHES,
    DEFAULT_N_CLUSTERS,
    PricingConfig,
    build_engine_context,
    find_value_bets,
)
from superbrain.engine.probability import (
    DEFAULT_MIN_MATCHES,
    DEFAULT_QUANTILE,
    ProbabilityConfig,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bets", tags=["bets"])


@router.get("/value", response_model=ValueBetsResponse)
async def list_value_bets(
    lake: Annotated[Lake, Depends(get_lake)],
    league: Annotated[str | None, Query()] = None,
    min_edge: Annotated[float, Query(ge=0.0, le=1.0)] = 0.0,
    markets: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    n_clusters: Annotated[int, Query(ge=2, le=32)] = DEFAULT_N_CLUSTERS,
    quantile: Annotated[float, Query(ge=0.0, le=1.0)] = DEFAULT_QUANTILE,
    min_matches: Annotated[int, Query(ge=1, le=100)] = DEFAULT_MIN_MATCHES,
    min_history_matches: Annotated[int, Query(ge=1, le=10_000)] = DEFAULT_MIN_HISTORY_MATCHES,
) -> ValueBetsResponse:
    """Price every upcoming fixture and surface its value bets.

    :param league: restrict to one league slug
    :param min_edge: minimum edge to emit (applied on top of the engine
        threshold; only stricter filters are honoured)
    :param markets: restrict to a subset of market codes
    :param limit: cap the number of returned rows
    :param n_clusters: number of agglomerative clusters (engine knob)
    :param quantile: neighbour-similarity quantile (engine knob)
    :param min_matches: minimum neighbour-pool size (engine knob)
    :param min_history_matches: minimum rows of team stats required
    """
    config = PricingConfig(
        n_clusters=n_clusters,
        probability=ProbabilityConfig(quantile=quantile, min_matches=min_matches),
    )
    items = await anyio.to_thread.run_sync(
        _compute_value_bets_sync,
        lake,
        league,
        float(min_edge),
        markets,
        int(limit),
        config,
        int(min_history_matches),
    )
    return ValueBetsResponse(
        items=items,
        count=len(items),
        computed_at=datetime.now(UTC),
    )


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


def _compute_value_bets_sync(
    lake: Lake,
    league: str | None,
    min_edge: float,
    markets: list[str] | None,
    limit: int,
    config: PricingConfig,
    min_history_matches: int,
) -> list[ValueBetItem]:
    """Load upcoming fixtures, price them, and return the flattened rows."""
    fixtures = _load_upcoming_fixtures(lake, league=league)
    if not fixtures:
        logger.info("bets/value: no upcoming fixtures found")
        return []

    market_set: list[Market] | None = None
    if markets:
        market_set = []
        for m in markets:
            try:
                market_set.append(Market(m))
            except ValueError:
                logger.warning("bets/value: unknown market %r, skipping", m)

    items: list[ValueBetItem] = []
    for fixture in fixtures:
        try:
            context = build_engine_context(
                lake,
                fixture=fixture,
                config=config,
                min_history_matches=min_history_matches,
            )
            if context is None:
                continue
            value_bets = find_value_bets(
                lake,
                fixture=fixture,
                edge_threshold=max(min_edge, 0.0),
                markets=market_set,
                config=config,
                context=context,
            )
        except (ValueError, KeyError, RuntimeError) as exc:  # pragma: no cover - defensive
            logger.warning(
                "bets/value: pricing failed for %s on %s (%s)",
                fixture.match_id,
                fixture.match_date,
                exc,
            )
            continue

        for vb in value_bets:
            items.append(
                ValueBetItem(
                    match_id=fixture.match_id,
                    match_label=f"{fixture.home_team} — {fixture.away_team}",
                    league=fixture.league.value,
                    market=vb.priced.outcome.market.value,
                    selection=vb.priced.outcome.selection,
                    market_params=dict(vb.priced.outcome.params),
                    bookmaker=vb.bookmaker,
                    decimal_odds=float(vb.decimal_odds),
                    book_prob=float(vb.book_probability),
                    model_prob=float(vb.priced.model_probability),
                    edge=float(vb.edge),
                    sample_size=int(vb.priced.sample_size),
                    captured_at=vb.captured_at,
                    kickoff_at=datetime.combine(
                        fixture.match_date, datetime.min.time(), tzinfo=UTC
                    ),
                )
            )
    items.sort(key=lambda x: x.edge, reverse=True)
    return items[:limit]


def _load_upcoming_fixtures(lake: Lake, *, league: str | None) -> list[Match]:
    """Read every match with ``match_date >= today`` and ``home_goals is null``."""
    today = date.today()
    frame = lake.read_matches(league=league, since=today)
    if frame.is_empty():
        return []
    frame = frame.filter(pl.col("home_goals").is_null() | pl.col("away_goals").is_null())
    fixtures: list[Match] = []
    for row in frame.sort(["match_date", "match_id"]).iter_rows(named=True):
        try:
            fixtures.append(_row_to_match(row))
        except (ValueError, KeyError):
            continue
    return fixtures


def _row_to_match(row: dict[str, Any]) -> Match:
    return Match(
        match_id=row["match_id"],
        league=League(row["league"]),
        season=row["season"],
        match_date=row["match_date"],
        home_team=row["home_team"],
        away_team=row["away_team"],
        home_goals=row.get("home_goals"),
        away_goals=row.get("away_goals"),
        source=row.get("source", "lake"),
        ingested_at=row.get("ingested_at") or datetime.now(UTC),
    )
