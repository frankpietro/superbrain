"""Backtest router.

Wraps :func:`superbrain.engine.backtest.run_backtest` as a synchronous HTTP
surface. The engine is fast on the slices the SPA sends (one league x one
season x optionally one market), so we return the full report in the
response body rather than streaming over SSE. If volumes ever force
streaming, swap the handler body for a ``StreamingResponse``; the schema
already fits a per-bet payload.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from superbrain.api.deps import get_lake
from superbrain.api.schemas import (
    BacktestBetRow,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestSummary,
)
from superbrain.core.markets import Market
from superbrain.core.models import League
from superbrain.data.connection import Lake
from superbrain.engine.backtest import (
    BacktestBet,
    BacktestReport,
    iter_fixtures_from_lake,
    run_backtest,
)
from superbrain.engine.pipeline import (
    DEFAULT_EDGE_THRESHOLD,
    DEFAULT_N_CLUSTERS,
    PricingConfig,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest", tags=["backtest"])


@router.post("/run", response_model=BacktestRunResponse)
async def run_backtest_endpoint(
    body: BacktestRunRequest,
    lake: Annotated[Lake, Depends(get_lake)],
) -> BacktestRunResponse:
    """Run a sliding-window backtest over a league x season.

    :param body: parsed request payload
    :param lake: injected process lake
    :return: summary numbers + per-bet rows
    :raises HTTPException: 400 when ``league`` or ``market`` do not
        resolve to a known enum value
    """
    try:
        league = League(body.league)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown league: {body.league}",
        ) from exc

    markets: list[Market] | None = None
    if body.market:
        try:
            markets = [Market(body.market)]
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown market: {body.market}",
            ) from exc

    fixtures = iter_fixtures_from_lake(lake, league=league, season=body.season)

    edge_cutoff = body.edge_cutoff if body.edge_cutoff is not None else DEFAULT_EDGE_THRESHOLD
    config = PricingConfig(n_clusters=body.n_clusters or DEFAULT_N_CLUSTERS)

    try:
        report = run_backtest(
            lake,
            fixtures=fixtures,
            edge_threshold=edge_cutoff,
            markets=markets,
            config=config,
            min_history_matches=body.min_history_matches,
            stake=body.stake,
        )
    except ValueError as exc:
        msg = str(exc)
        if "clusters" in msg or "samples" in msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"not enough history to cluster teams (n_clusters={config.n_clusters}): "
                    f"{msg}. Try lowering n_clusters or selecting a season with more fixtures."
                ),
            ) from exc
        raise

    if body.threshold is not None:
        kept = [b for b in report.bets if _matches_threshold(b, body.threshold)]
        bets = [_bet_to_row(b) for b in kept]
        summary = _summary_from(kept, fallback_sharpe=report.sharpe if not kept else 0.0)
    else:
        bets = [_bet_to_row(b) for b in report.bets]
        summary = _summary_full(report)

    return BacktestRunResponse(
        request=body,
        fixtures_considered=len(fixtures),
        summary=summary,
        bets=bets,
    )


def _bet_to_row(bet: BacktestBet) -> BacktestBetRow:
    vb = bet.value_bet
    return BacktestBetRow(
        match_id=bet.fixture.match_id,
        match_date=bet.fixture.match_date.isoformat(),
        home_team=bet.fixture.home_team,
        away_team=bet.fixture.away_team,
        market=vb.priced.outcome.market.value,
        selection=vb.priced.outcome.selection,
        bookmaker=vb.bookmaker,
        decimal_odds=vb.decimal_odds,
        model_probability=vb.priced.model_probability,
        edge=vb.edge,
        stake=bet.stake,
        won=bet.won,
        payout=bet.payout,
        profit=bet.profit,
    )


def _summary_full(report: BacktestReport) -> BacktestSummary:
    return BacktestSummary(
        n_bets=report.n_bets,
        n_wins=report.n_wins,
        n_losses=report.n_losses,
        n_unresolved=report.n_unresolved,
        total_stake=report.total_stake,
        total_profit=report.total_profit,
        roi=report.roi,
        hit_rate=report.hit_rate,
        sharpe=report.sharpe,
    )


def _summary_from(bets: list[BacktestBet], *, fallback_sharpe: float) -> BacktestSummary:
    """Recompute aggregates after a client-side filter.

    Keeps the invariants ``n_wins + n_losses + n_unresolved == n_bets`` and
    ``roi == total_profit / total_stake`` true on the filtered set.
    Sharpe is not recomputed here; callers pass a fallback.
    """
    n_wins = sum(1 for b in bets if b.won is True)
    n_losses = sum(1 for b in bets if b.won is False)
    n_unresolved = sum(1 for b in bets if b.won is None)
    total_stake = sum(b.stake for b in bets if b.won is not None)
    total_profit = sum(b.profit for b in bets)
    roi = total_profit / total_stake if total_stake > 0 else 0.0
    settled = n_wins + n_losses
    hit_rate = n_wins / settled if settled > 0 else 0.0
    return BacktestSummary(
        n_bets=len(bets),
        n_wins=n_wins,
        n_losses=n_losses,
        n_unresolved=n_unresolved,
        total_stake=total_stake,
        total_profit=total_profit,
        roi=roi,
        hit_rate=hit_rate,
        sharpe=fallback_sharpe,
    )


def _matches_threshold(bet: BacktestBet, threshold: float) -> bool:
    """Best-effort filter; keep the bet when the market has no threshold."""
    params = bet.value_bet.priced.outcome.params
    if "threshold" not in params:
        return True
    try:
        return float(params["threshold"]) == float(threshold)
    except (TypeError, ValueError):
        return True
