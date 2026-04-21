"""Top-level pricing + value-bet orchestration.

The pipeline stitches the engine primitives together:

1. Read historical matches + team-match stats from the lake *strictly
   before* the fixture's kickoff (no-leakage invariant).
2. Cluster (cosine / average-linkage) + merge-opponent-clusters.
3. Build the (team, season) similarity matrix.
4. For every requested market, iterate odds rows, materialise
   :class:`~superbrain.engine.bets.base.Outcome` values, collect the
   neighbor sample, and compute the model probability.
5. ``find_value_bets`` joins the pricing output against
   :class:`~superbrain.core.models.OddsSnapshot` rows, picks the latest
   snapshot per ``(market, selection, params)``, and computes the edge.

Nothing in this module touches a bookmaker directly; it's pure
in-lake computation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import polars as pl

from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League, Match, OddsSnapshot
from superbrain.data.connection import Lake
from superbrain.engine.bets.base import EngineContext, Outcome
from superbrain.engine.bets.registry import (
    BET_REGISTRY,
    registered_markets,
)
from superbrain.engine.clustering import (
    ClusterAssignment,
    cluster_teams,
    merge_opponent_clusters,
    prepare_team_match_stats,
)
from superbrain.engine.probability import (
    DEFAULT_MIN_MATCHES,
    DEFAULT_QUANTILE,
    ProbabilityConfig,
    collect_neighbor_values,
)
from superbrain.engine.similarity import (
    build_similarity_matrix,
    similarity_threshold,
)

logger = logging.getLogger(__name__)

DEFAULT_N_CLUSTERS: Final = 8
DEFAULT_EDGE_THRESHOLD: Final = 0.05
DEFAULT_MIN_HISTORY_MATCHES: Final = 60

DEFAULT_FEATURE_COLUMNS: Final = (
    "goals",
    "goals_conceded",
    "shots",
    "shots_on_target",
    "corners",
    "yellow_cards",
    "fouls",
)


@dataclass(frozen=True)
class PricingConfig:
    """Pricing knobs. Defaults mirror the old repo's production settings.

    :ivar n_clusters: clustering target count.
    :ivar feature_columns: ``TeamMatchStats`` columns fed to the clusterer.
    :ivar probability: neighbor-pool quantile + minimum-sample-size gate.
    """

    n_clusters: int = DEFAULT_N_CLUSTERS
    feature_columns: tuple[str, ...] = DEFAULT_FEATURE_COLUMNS
    probability: ProbabilityConfig = field(
        default_factory=lambda: ProbabilityConfig(
            quantile=DEFAULT_QUANTILE, min_matches=DEFAULT_MIN_MATCHES
        )
    )


@dataclass(frozen=True)
class PricedOutcome:
    """A priced outcome with its supporting evidence.

    :ivar fixture: the fixture this pricing belongs to.
    :ivar outcome: the market + selection + params triple.
    :ivar model_probability: probability in ``[0, 1]``.
    :ivar model_payout: inverse probability (``10000.0`` when prob==0).
    :ivar sample_size: number of neighbor matches contributing per side.
    :ivar target_columns: which ``TeamMatchStats`` columns were used.
    """

    fixture: Match
    outcome: Outcome
    model_probability: float
    model_payout: float
    sample_size: int
    target_columns: list[str]


@dataclass(frozen=True)
class ValueBet:
    """A value bet: model probability > book-implied probability.

    :ivar fixture: priced fixture.
    :ivar priced: the underlying :class:`PricedOutcome`.
    :ivar bookmaker: bookmaker slug.
    :ivar decimal_odds: bookmaker's decimal odds at ``captured_at``.
    :ivar book_probability: ``1 / decimal_odds``.
    :ivar edge: ``model_probability - book_probability`` (positive
        means value).
    :ivar captured_at: when the selected snapshot was observed.
    """

    fixture: Match
    priced: PricedOutcome
    bookmaker: str
    decimal_odds: float
    book_probability: float
    edge: float
    captured_at: datetime


def _season_code_for(match_date: date) -> str:
    """Derive a season code like ``"2024-25"`` from a fixture date.

    Mirrors the layout of :class:`~superbrain.core.models.Season`.
    """
    start_year = match_date.year if match_date.month >= 7 else match_date.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def build_engine_context(
    lake: Lake,
    *,
    fixture: Match,
    config: PricingConfig | None = None,
    min_history_matches: int = DEFAULT_MIN_HISTORY_MATCHES,
) -> EngineContext | None:
    """Read historical lake state up to ``fixture.match_date`` and cluster it.

    :param lake: lake handle.
    :param fixture: the fixture being priced.
    :param config: pricing configuration.
    :param min_history_matches: minimum number of historical ``team_match_stats``
        rows required to proceed; below this, pricing is impossible and we
        return ``None``.
    :return: :class:`EngineContext` or ``None`` when history is too thin
        or the lake has no stats.
    """
    if config is None:
        config = PricingConfig()
    matches_df = lake.read_matches()
    stats_df = _read_team_match_stats(lake)

    cutoff = fixture.match_date
    if not stats_df.is_empty() and "match_date" in stats_df.columns:
        stats_df = stats_df.filter(pl.col("match_date") < cutoff)
    if not matches_df.is_empty() and "match_date" in matches_df.columns:
        matches_df = matches_df.filter(pl.col("match_date") < cutoff)

    if stats_df.height < min_history_matches:
        logger.warning(
            "pipeline: not enough history (%d < %d), returning None",
            stats_df.height,
            min_history_matches,
        )
        return None

    with_opponent = prepare_team_match_stats(stats_df, matches=matches_df)
    assignment = cluster_teams(
        with_opponent,
        n_clusters=config.n_clusters,
        columns_of_interest=list(config.feature_columns),
        training_cutoff=cutoff,
    )
    if assignment.is_empty:
        return None
    assignment = merge_opponent_clusters(assignment)
    similarity = build_similarity_matrix(assignment)

    return EngineContext(
        stats_df=assignment.data,
        similarity=similarity,
        assignment=_downgrade_assignment(assignment),
        config=config.probability,
    )


def price_fixture(
    lake: Lake,
    *,
    fixture: Match,
    odds_snapshots: Iterable[OddsSnapshot] | None = None,
    markets: Iterable[Market] | None = None,
    config: PricingConfig | None = None,
    min_history_matches: int = DEFAULT_MIN_HISTORY_MATCHES,
    context: EngineContext | None = None,
) -> list[PricedOutcome]:
    """Compute model probabilities for every outcome exposed on a fixture.

    Outcomes are enumerated per registered strategy by iterating
    ``odds_snapshots``. Passing ``odds_snapshots=None`` reads the lake.

    :param lake: lake handle
    :param fixture: the fixture to price (``Match`` pydantic model)
    :param odds_snapshots: optional precomputed odds iterable; when ``None``,
        the fixture's snapshots are read from the lake
    :param markets: restrict to a subset of registered markets (default:
        all registered)
    :param config: pricing configuration
    :param min_history_matches: floor gate on historical stats
    :param context: optional precomputed :class:`EngineContext` (saves
        recomputation when pricing many fixtures on the same day)
    :return: list of :class:`PricedOutcome`
    """
    if config is None:
        config = PricingConfig()
    selected = list(markets) if markets is not None else registered_markets()
    if not selected:
        return []

    if odds_snapshots is None:
        odds_snapshots = _read_odds_for_fixture(lake, fixture)
    snapshots_by_market = _group_snapshots_by_market(odds_snapshots, selected)

    if not any(snapshots_by_market.values()):
        return []

    ctx = context or build_engine_context(
        lake,
        fixture=fixture,
        config=config,
        min_history_matches=min_history_matches,
    )
    if ctx is None:
        return []

    season = fixture.season
    threshold = similarity_threshold(ctx.similarity, ctx.config.quantile)

    priced: list[PricedOutcome] = []
    outcome_cache: dict[str, tuple[list[float], list[float]]] = {}

    for market in selected:
        snapshots = snapshots_by_market.get(market, [])
        if not snapshots:
            continue
        strategy = BET_REGISTRY.get(market)
        if strategy is None:
            continue

        for outcome in strategy.iter_outcomes(snapshots):
            target_cols = strategy.target_stat_columns(outcome)
            primary_col = target_cols[0] if target_cols else "goals"

            cache_key = f"{primary_col}|{fixture.home_team}|{fixture.away_team}|{season}"
            sample = outcome_cache.get(cache_key)
            if sample is None:
                sample = collect_neighbor_values(
                    sim=ctx.similarity,
                    target_index=ctx.target_index(primary_col),
                    home_team=fixture.home_team,
                    away_team=fixture.away_team,
                    season=season,
                    config=ctx.config,
                    threshold=threshold,
                )
                outcome_cache[cache_key] = sample

            values_home, values_away = sample
            if not values_home or not values_away:
                continue

            probability = strategy.compute_probability(
                outcome, values_home=values_home, values_away=values_away
            )
            probability = max(0.0, min(1.0, probability))
            model_payout = 1.0 / probability if probability > 0 else 10000.0
            sample_size = min(len(values_home), len(values_away))

            priced.append(
                PricedOutcome(
                    fixture=fixture,
                    outcome=outcome,
                    model_probability=probability,
                    model_payout=model_payout,
                    sample_size=sample_size,
                    target_columns=list(target_cols),
                )
            )

    logger.info(
        "price_fixture: %s vs %s on %s → %d priced outcomes",
        fixture.home_team,
        fixture.away_team,
        fixture.match_date,
        len(priced),
    )
    return priced


def find_value_bets(
    lake: Lake,
    *,
    fixture: Match,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    markets: Iterable[Market] | None = None,
    config: PricingConfig | None = None,
    odds_snapshots: Iterable[OddsSnapshot] | None = None,
    context: EngineContext | None = None,
    latest_snapshot_per_selection: bool = True,
) -> list[ValueBet]:
    """Surface bets where ``model_probability - 1 / decimal_odds > edge_threshold``.

    :param lake: lake handle
    :param fixture: fixture to price
    :param edge_threshold: minimum edge to emit (default 0.05)
    :param markets: restrict to a subset of markets
    :param config: pricing configuration
    :param odds_snapshots: optional precomputed odds iterable
    :param context: optional precomputed engine context
    :param latest_snapshot_per_selection: when ``True``, each
        ``(bookmaker, market, selection, params)`` tuple is priced
        against its most recent snapshot only
    :return: list of :class:`ValueBet`, sorted by descending edge
    """
    if config is None:
        config = PricingConfig()
    if odds_snapshots is None:
        odds_snapshots = _read_odds_for_fixture(lake, fixture)
    snapshots = list(odds_snapshots)

    priced = price_fixture(
        lake,
        fixture=fixture,
        odds_snapshots=snapshots,
        markets=markets,
        config=config,
        context=context,
    )
    if not priced:
        return []

    if latest_snapshot_per_selection:
        selected_snapshots = _latest_per_selection(snapshots)
    else:
        selected_snapshots = snapshots

    by_key: dict[tuple[str, str, str, str], list[OddsSnapshot]] = {}
    for snap in selected_snapshots:
        key = (
            snap.bookmaker.value,
            snap.market.value,
            snap.selection,
            snap.params_hash(),
        )
        by_key.setdefault(key, []).append(snap)

    value_bets: list[ValueBet] = []
    for p in priced:
        outcome_hash = _outcome_params_hash(p.outcome.params)
        for bookmaker_val, snaps in _iter_snapshots_for_outcome(by_key, p.outcome):
            if not snaps:
                continue
            snap = max(snaps, key=lambda s: s.captured_at)
            if snap.params_hash() != outcome_hash and not _approx_params_match(
                snap.market_params, p.outcome.params
            ):
                continue
            decimal_odds = float(snap.payout)
            if decimal_odds <= 1.0:
                continue
            book_prob = 1.0 / decimal_odds
            edge = p.model_probability - book_prob
            if edge <= edge_threshold:
                continue
            value_bets.append(
                ValueBet(
                    fixture=fixture,
                    priced=p,
                    bookmaker=bookmaker_val,
                    decimal_odds=decimal_odds,
                    book_probability=book_prob,
                    edge=edge,
                    captured_at=snap.captured_at,
                )
            )

    value_bets.sort(key=lambda vb: vb.edge, reverse=True)
    return value_bets


def _iter_snapshots_for_outcome(
    by_key: dict[tuple[str, str, str, str], list[OddsSnapshot]],
    outcome: Outcome,
) -> Iterable[tuple[str, list[OddsSnapshot]]]:
    """Yield ``(bookmaker, snapshots)`` for every bookmaker offering ``outcome``."""
    outcome_hash = _outcome_params_hash(outcome.params)
    per_bookmaker: dict[str, list[OddsSnapshot]] = {}
    for (bm, market_val, selection, params_hash), snaps in by_key.items():
        if market_val != outcome.market.value or selection != outcome.selection:
            continue
        if params_hash == outcome_hash:
            per_bookmaker.setdefault(bm, []).extend(snaps)
            continue
        if snaps and _approx_params_match(snaps[0].market_params, outcome.params):
            per_bookmaker.setdefault(bm, []).extend(snaps)
    yield from per_bookmaker.items()


def _approx_params_match(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if set(a) != set(b):
        return False
    for k, av in a.items():
        bv = b[k]
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            if abs(float(av) - float(bv)) > 1e-9:
                return False
        elif str(av) != str(bv):
            return False
    return True


def _outcome_params_hash(params: dict[str, Any]) -> str:
    payload = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _latest_per_selection(snapshots: Iterable[OddsSnapshot]) -> list[OddsSnapshot]:
    latest: dict[tuple[str, str, str, str], OddsSnapshot] = {}
    for s in snapshots:
        key = (s.bookmaker.value, s.market.value, s.selection, s.params_hash())
        current = latest.get(key)
        if current is None or s.captured_at > current.captured_at:
            latest[key] = s
    return list(latest.values())


def _group_snapshots_by_market(
    snapshots: Iterable[OddsSnapshot],
    markets: list[Market],
) -> dict[Market, list[OddsSnapshot]]:
    wanted = set(markets)
    out: dict[Market, list[OddsSnapshot]] = {m: [] for m in wanted}
    for s in snapshots:
        if s.market in wanted:
            out[s.market].append(s)
    return out


def _read_odds_for_fixture(lake: Lake, fixture: Match) -> list[OddsSnapshot]:
    """Read every odds snapshot that matches this fixture's ``(match_id, match_date)``.

    The lake exposes :meth:`Lake.read_odds`; we filter client-side on
    ``match_id`` (and fall back to ``home_team``/``away_team``/``match_date``
    for legacy rows that lack a ``match_id``).
    """
    df = lake.read_odds(season=fixture.season)
    if df.is_empty():
        return []

    df = df.filter(
        (pl.col("match_id") == fixture.match_id)
        | (
            (pl.col("match_date") == fixture.match_date)
            & (pl.col("home_team") == fixture.home_team)
            & (pl.col("away_team") == fixture.away_team)
        )
    )
    if df.is_empty():
        return []

    results: list[OddsSnapshot] = []
    for row in df.iter_rows(named=True):
        try:
            results.append(_row_to_snapshot(row))
        except (ValueError, KeyError):
            continue
    return results


def _row_to_snapshot(row: dict[str, Any]) -> OddsSnapshot:
    params_raw = row.get("market_params_json")
    params = json.loads(params_raw) if params_raw else {}
    league_val = row.get("league")
    league = League(league_val) if league_val else None

    captured_at = row["captured_at"]
    if isinstance(captured_at, datetime) and captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)

    return OddsSnapshot(
        bookmaker=Bookmaker(row["bookmaker"]),
        bookmaker_event_id=row["bookmaker_event_id"],
        match_id=row.get("match_id"),
        match_label=row["match_label"],
        match_date=row["match_date"],
        season=row["season"],
        league=league,
        home_team=row["home_team"],
        away_team=row["away_team"],
        market=Market(row["market"]),
        market_params=params,
        selection=row["selection"],
        payout=float(row["payout"]),
        captured_at=captured_at,
        source=row["source"],
        run_id=row["run_id"],
        raw_json=row.get("raw_json"),
    )


def _read_team_match_stats(lake: Lake) -> pl.DataFrame:
    """Read every ``team_match_stats`` partition as a single polars frame."""
    root = lake.layout.team_match_stats_root
    if not root.exists():
        return pl.DataFrame(
            schema={
                "match_id": pl.String,
                "team": pl.String,
                "is_home": pl.Boolean,
                "league": pl.String,
                "season": pl.String,
                "match_date": pl.Date,
            }
        )
    paths = sorted(root.glob("league=*/season=*/*.parquet"))
    if not paths:
        return pl.DataFrame(
            schema={
                "match_id": pl.String,
                "team": pl.String,
                "is_home": pl.Boolean,
                "league": pl.String,
                "season": pl.String,
                "match_date": pl.Date,
            }
        )
    return pl.read_parquet(paths)


def _downgrade_assignment(assignment: ClusterAssignment) -> ClusterAssignment:
    """Return a lighter copy of ``assignment`` for storage in the context.

    We keep the frame and the team-to-cluster map, strip the opponent merge
    if it's big (not needed after similarity is built).
    """
    return assignment


def season_for_date(match_date: date) -> str:
    """Convenience wrapper for downstream callers."""
    return _season_code_for(match_date)


def daterange(start: date, end: date) -> Iterable[date]:
    """Inclusive date iterator used by the backtest harness."""
    d = start
    while d <= end:
        yield d
        d = d + timedelta(days=1)
