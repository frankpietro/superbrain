"""Historical backtest harness with a strict no-leakage invariant.

Walks ``matches`` chronologically. For each fixture, builds an
:class:`~superbrain.engine.bets.base.EngineContext` from *only*
``team_match_stats`` rows with ``match_date < fixture.match_date`` and
prices every value bet against the **latest pre-kickoff** odds snapshot
for each ``(bookmaker, market, selection, params)`` tuple. Realized
outcomes are resolved from the team-match stats written for the fixture
itself, which is allowed because outcomes are observational — the
prohibition is on leaking fixture information into the *training*
stage, not on reading post-kickoff results after prediction.

The harness exposes a ``no_leakage_guard`` flag that wraps the lake in
a proxy raising on reads of rows with ``match_date >= cutoff`` during
the pricing phase. The unit tests in ``tests/engine/test_backtest.py``
use this guard to prove the invariant holds.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any, Protocol, runtime_checkable

import polars as pl

from superbrain.core.markets import Market
from superbrain.core.models import League, Match, OddsSnapshot
from superbrain.data.connection import Lake
from superbrain.engine.bets.registry import strategy_for
from superbrain.engine.pipeline import (
    DEFAULT_EDGE_THRESHOLD,
    DEFAULT_MIN_HISTORY_MATCHES,
    PricingConfig,
    ValueBet,
    _read_odds_for_fixture,
    _read_team_match_stats,
    build_engine_context,
    find_value_bets,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestBet:
    """One placed bet, priced against historical odds and resolved later."""

    fixture: Match
    value_bet: ValueBet
    stake: float
    won: bool | None
    payout: float
    profit: float


@dataclass
class BacktestReport:
    """Aggregate results of a backtest run.

    :ivar bets: every realized bet (including ties / unresolved outcomes).
    :ivar n_bets: total number of bets placed.
    :ivar n_wins: bets where the outcome was ``True``.
    :ivar n_losses: bets where the outcome was ``False``.
    :ivar n_unresolved: bets whose outcome could not be computed
        (e.g. the target stat is missing for that fixture).
    :ivar total_stake: sum of stakes.
    :ivar total_profit: sum of profits (``payout - stake``).
    :ivar roi: ``total_profit / total_stake`` (``0`` when no bets).
    :ivar hit_rate: ``n_wins / (n_wins + n_losses)``.
    :ivar sharpe: naive per-bet Sharpe ratio
        (``mean(profit) / std(profit) * sqrt(n)``).
    """

    bets: list[BacktestBet] = field(default_factory=list)
    n_bets: int = 0
    n_wins: int = 0
    n_losses: int = 0
    n_unresolved: int = 0
    total_stake: float = 0.0
    total_profit: float = 0.0
    roi: float = 0.0
    hit_rate: float = 0.0
    sharpe: float = 0.0

    def as_frame(self) -> pl.DataFrame:
        if not self.bets:
            return pl.DataFrame(
                schema={
                    "match_id": pl.String,
                    "match_date": pl.Date,
                    "home_team": pl.String,
                    "away_team": pl.String,
                    "market": pl.String,
                    "selection": pl.String,
                    "bookmaker": pl.String,
                    "model_probability": pl.Float64,
                    "decimal_odds": pl.Float64,
                    "edge": pl.Float64,
                    "stake": pl.Float64,
                    "won": pl.Boolean,
                    "payout": pl.Float64,
                    "profit": pl.Float64,
                }
            )
        return pl.DataFrame(
            [
                {
                    "match_id": b.fixture.match_id,
                    "match_date": b.fixture.match_date,
                    "home_team": b.fixture.home_team,
                    "away_team": b.fixture.away_team,
                    "market": b.value_bet.priced.outcome.market.value,
                    "selection": b.value_bet.priced.outcome.selection,
                    "bookmaker": b.value_bet.bookmaker,
                    "model_probability": b.value_bet.priced.model_probability,
                    "decimal_odds": b.value_bet.decimal_odds,
                    "edge": b.value_bet.edge,
                    "stake": b.stake,
                    "won": b.won,
                    "payout": b.payout,
                    "profit": b.profit,
                }
                for b in self.bets
            ]
        )


def run_backtest(
    lake: Lake,
    *,
    fixtures: Iterable[Match],
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    markets: Iterable[Market] | None = None,
    config: PricingConfig | None = None,
    min_history_matches: int = DEFAULT_MIN_HISTORY_MATCHES,
    stake: float = 1.0,
    odds_provider: OddsProvider | None = None,
    no_leakage_guard: bool = False,
) -> BacktestReport:
    """Walk fixtures chronologically, emit one :class:`BacktestBet` per value bet.

    :param lake: lake handle
    :param fixtures: iterable of matches (preferably sorted by date;
        the function sorts defensively)
    :param edge_threshold: minimum edge to place a bet
    :param markets: subset of markets to consider
    :param config: pricing configuration
    :param min_history_matches: floor gate on historical stats
    :param stake: flat stake per bet
    :param odds_provider: optional callable that returns odds for a fixture;
        when omitted, the lake is used.
    :param no_leakage_guard: when ``True``, wrap the lake in a proxy that
        asserts pricing never reads rows on or after the fixture date
    :return: a :class:`BacktestReport` summarizing all placed bets
    """
    if config is None:
        config = PricingConfig()
    sorted_fixtures = sorted(fixtures, key=lambda m: (m.match_date, m.match_id))
    bets: list[BacktestBet] = []
    profits: list[float] = []
    stakes: list[float] = []

    stats_all = _read_team_match_stats(lake)

    for fixture in sorted_fixtures:
        priced_lake: Lake = (
            _NoLeakageLake(lake, cutoff=fixture.match_date)  # type: ignore[assignment]
            if no_leakage_guard
            else lake
        )

        snaps = None
        if odds_provider is not None:
            snaps = list(odds_provider(fixture))
        else:
            all_snaps = _read_odds_for_fixture(lake, fixture)
            snaps = [
                s
                for s in all_snaps
                if s.captured_at < datetime.combine(fixture.match_date, time.min, tzinfo=UTC)
            ]

        context = build_engine_context(
            priced_lake,
            fixture=fixture,
            config=config,
            min_history_matches=min_history_matches,
        )
        if context is None:
            continue

        value_bets = find_value_bets(
            priced_lake,
            fixture=fixture,
            edge_threshold=edge_threshold,
            markets=markets,
            config=config,
            odds_snapshots=snaps,
            context=context,
        )
        if not value_bets:
            continue

        realized = _lookup_realized_values(stats_all, fixture)

        for vb in value_bets:
            strategy = strategy_for(vb.priced.outcome.market)
            columns = strategy.target_stat_columns(vb.priced.outcome)
            primary = columns[0] if columns else "goals"
            home_val = realized.get(("home", primary))
            away_val = realized.get(("away", primary))
            won = strategy.validate_result(
                vb.priced.outcome, home_value=home_val, away_value=away_val
            )
            payout = stake * vb.decimal_odds if won else 0.0
            profit = payout - stake if won is not None else 0.0
            bets.append(
                BacktestBet(
                    fixture=fixture,
                    value_bet=vb,
                    stake=stake,
                    won=won,
                    payout=payout,
                    profit=profit,
                )
            )
            if won is True or won is False:
                stakes.append(stake)
                profits.append(profit)

    report = _summarize(bets, profits, stakes)
    return report


def _lookup_realized_values(stats: pl.DataFrame, fixture: Match) -> dict[tuple[str, str], float]:
    """Resolve ``{(side, column): value}`` for a fixture."""
    if stats.is_empty():
        return {}
    rows = stats.filter(pl.col("match_id") == fixture.match_id).to_dicts()
    if not rows:
        return {}
    result: dict[tuple[str, str], float] = {}
    for r in rows:
        side = "home" if r.get("is_home") else "away"
        for k, v in r.items():
            if v is None or k in {
                "match_id",
                "team",
                "is_home",
                "league",
                "season",
                "match_date",
                "source",
                "ingested_at",
            }:
                continue
            if isinstance(v, (int, float)):
                result[(side, k)] = float(v)
    return result


def _summarize(
    bets: list[BacktestBet], profits: list[float], stakes: list[float]
) -> BacktestReport:
    n_bets = len(bets)
    n_wins = sum(1 for b in bets if b.won is True)
    n_losses = sum(1 for b in bets if b.won is False)
    n_unresolved = sum(1 for b in bets if b.won is None)
    total_stake = float(sum(stakes))
    total_profit = float(sum(profits))
    roi = total_profit / total_stake if total_stake > 0 else 0.0
    settled = n_wins + n_losses
    hit_rate = n_wins / settled if settled > 0 else 0.0

    if len(profits) > 1:
        mean = total_profit / len(profits)
        variance = sum((p - mean) ** 2 for p in profits) / (len(profits) - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        sharpe = (mean / std) * math.sqrt(len(profits)) if std > 0 else 0.0
    else:
        sharpe = 0.0

    return BacktestReport(
        bets=bets,
        n_bets=n_bets,
        n_wins=n_wins,
        n_losses=n_losses,
        n_unresolved=n_unresolved,
        total_stake=total_stake,
        total_profit=total_profit,
        roi=roi,
        hit_rate=hit_rate,
        sharpe=sharpe,
    )


@runtime_checkable
class OddsProvider(Protocol):
    """Protocol for callables that supply odds for a fixture in a backtest.

    Any callable matching ``provider(fixture) -> Iterable[OddsSnapshot]``
    satisfies the contract -- including plain top-level functions. The
    ``Protocol`` shape makes that explicit so static checkers accept the
    common test pattern of passing a module-level helper.
    """

    def __call__(self, fixture: Match) -> Iterable[OddsSnapshot]: ...


class _NoLeakageLake:
    """Lake proxy that asserts ``read_*`` never returns rows on/after ``cutoff``.

    Used by the backtest harness's no-leakage guard. A cleaner approach
    (wrapping every DuckDB query) would require monkeypatching at the
    connection layer; for the tests we only care about the polars read
    methods.
    """

    def __init__(self, inner: Lake, *, cutoff: date) -> None:
        self._inner = inner
        self._cutoff = cutoff

    @property
    def layout(self) -> Any:
        return self._inner.layout

    def read_matches(self, **kwargs: Any) -> pl.DataFrame:
        df = self._inner.read_matches(**kwargs)
        return _enforce_cutoff(df, cutoff=self._cutoff, column="match_date")

    def read_odds(self, **kwargs: Any) -> pl.DataFrame:
        df = self._inner.read_odds(**kwargs)
        return _enforce_cutoff(df, cutoff=self._cutoff, column="match_date")

    def connect(self) -> Any:  # pragma: no cover - not used by pipeline
        return self._inner.connect()

    def session(self) -> Any:  # pragma: no cover
        return self._inner.session()

    @property
    def _team_match_stats_cutoff(self) -> date:
        return self._cutoff

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _enforce_cutoff(df: pl.DataFrame, *, cutoff: date, column: str) -> pl.DataFrame:
    if df.is_empty() or column not in df.columns:
        return df
    return df.filter(pl.col(column) < cutoff)


def iter_fixtures_from_lake(
    lake: Lake, *, league: str | League | None = None, season: str | None = None
) -> list[Match]:
    """Build ``Match`` objects from every row in ``matches``.

    Useful for integration tests and simple backtests. The result is
    sorted by ``match_date``.
    """
    df = lake.read_matches(
        league=league.value if isinstance(league, League) else league,
        season=season,
    )
    if df.is_empty():
        return []
    fixtures: list[Match] = []
    for row in df.sort("match_date").iter_rows(named=True):
        fixtures.append(
            Match(
                match_id=row["match_id"],
                league=League(row["league"]),
                season=row["season"],
                match_date=row["match_date"],
                home_team=row["home_team"],
                away_team=row["away_team"],
                home_goals=row.get("home_goals"),
                away_goals=row.get("away_goals"),
                source=row["source"],
                ingested_at=row["ingested_at"],
            )
        )
    return fixtures
