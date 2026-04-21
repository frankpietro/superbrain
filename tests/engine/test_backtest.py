"""End-to-end backtest harness tests with a no-leakage guard.

Covers the three phase-4b contracts from ``docs/knowledge.md`` (follow-up
item 2):

1. ``run_backtest`` returns a consistent :class:`BacktestReport` where
   ``n_wins + n_losses + n_unresolved == n_bets`` and ROI is exactly
   ``total_profit / total_stake``.
2. ROI math is reproduced by a hand-computed golden using a controlled
   ``odds_provider`` that forces one deterministic value bet per
   fixture.
3. ``_NoLeakageLake`` wrapped around the lake prevents *any* read of
   rows from the match-of-interest (constructive: wrap, read, assert
   the held-out match-id never appears in either ``read_matches`` or
   ``read_odds`` output).
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from superbrain.core.markets import Market
from superbrain.core.models import (
    Bookmaker,
    IngestProvenance,
    League,
    Match,
    OddsSnapshot,
    TeamMatchStats,
    compute_match_id,
)
from superbrain.data.connection import Lake
from superbrain.engine.backtest import (
    BacktestReport,
    _NoLeakageLake,
    run_backtest,
)
from superbrain.engine.pipeline import PricingConfig
from superbrain.engine.probability import ProbabilityConfig

BACKTEST_SEASON = "2023-24"
BACKTEST_LEAGUE = League.SERIE_A
BACKTEST_TEAMS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
BACKTEST_CONFIG = PricingConfig(
    n_clusters=2,
    probability=ProbabilityConfig(quantile=0.3, min_matches=3),
)


def _pos(value: float) -> int:
    return max(0, round(value))


def _seed_lake(tmp_path: Path, *, seed: int = 13) -> tuple[Lake, list[Match]]:
    """Build a deterministic 10-match synthetic lake used by the backtest tests."""
    rng = random.Random(seed)
    ingested = datetime(2024, 6, 1, tzinfo=UTC)
    lake = Lake(root=tmp_path / "lake")
    lake.ensure_schema()

    style = {t: rng.gauss(0.0, 1.0) for t in BACKTEST_TEAMS}

    pairs: list[tuple[str, str]] = []
    for i, home in enumerate(BACKTEST_TEAMS):
        for away in BACKTEST_TEAMS[i + 1 :]:
            pairs.append((home, away))
            pairs.append((away, home))
    pairs = pairs[:10]

    day0 = date(2023, 8, 1)
    matches: list[Match] = []
    stats: list[TeamMatchStats] = []

    for idx, (home, away) in enumerate(pairs):
        match_date = day0 + timedelta(days=idx * 3)
        home_goals = rng.randint(0, 3)
        away_goals = rng.randint(0, 3)
        mid = compute_match_id(home, away, match_date, BACKTEST_LEAGUE)
        matches.append(
            Match(
                match_id=mid,
                league=BACKTEST_LEAGUE,
                season=BACKTEST_SEASON,
                match_date=match_date,
                home_team=home,
                away_team=away,
                home_goals=home_goals,
                away_goals=away_goals,
                source="backtest-test",
                ingested_at=ingested,
            )
        )
        for team, opp, is_home, goals in (
            (home, away, True, home_goals),
            (away, home, False, away_goals),
        ):
            bias = style[team] - style[opp]
            stats.append(
                TeamMatchStats(
                    match_id=mid,
                    team=team,
                    is_home=is_home,
                    league=BACKTEST_LEAGUE,
                    season=BACKTEST_SEASON,
                    match_date=match_date,
                    goals=goals,
                    goals_conceded=(away_goals if is_home else home_goals),
                    shots=_pos(11 + 2 * bias + rng.gauss(0, 2)),
                    shots_on_target=_pos(4 + bias + rng.gauss(0, 1.2)),
                    corners=_pos(5 + bias + rng.gauss(0, 1.5)),
                    yellow_cards=_pos(2 + rng.gauss(0, 1)),
                    fouls=_pos(11 + rng.gauss(0, 2)),
                    red_cards=0,
                    source="backtest-test",
                    ingested_at=ingested,
                )
            )

    prov = IngestProvenance(
        source="backtest-test",
        run_id="backtest",
        actor="test",
        captured_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    lake.ingest_matches(matches, provenance=prov)
    lake.ingest_team_match_stats(stats, provenance=prov)
    return lake, matches


def _force_goals_over_provider(
    fixture: Match,
) -> Iterable[OddsSnapshot]:
    """Emit a single OVER 0.5 snapshot per fixture with very short odds.

    Picking ``threshold = 0.5`` and ``payout = 1.20`` guarantees:

    * pricing: the engine's neighbour pool for ``goals`` will produce
      ``prob >> 1 / 1.20 = 0.833`` as soon as any match scored a goal,
      so an edge materialises for every fixture with enough history.
    * resolution: ``home_goals + away_goals >= 0.5`` iff at least one
      goal was scored — lets the hand-computed ROI be derived
      mechanically from each fixture's realized goals.
    """
    captured_at = datetime.combine(fixture.match_date, datetime.min.time(), tzinfo=UTC) - timedelta(
        hours=3
    )
    return [
        OddsSnapshot(
            bookmaker=Bookmaker.SISAL,
            bookmaker_event_id=f"evt-{fixture.match_id}",
            match_id=fixture.match_id,
            match_label=f"{fixture.home_team}-{fixture.away_team}",
            match_date=fixture.match_date,
            season=fixture.season,
            league=fixture.league,
            home_team=fixture.home_team,
            away_team=fixture.away_team,
            market=Market.GOALS_OVER_UNDER,
            market_params={"threshold": 0.5},
            selection="OVER",
            payout=1.20,
            captured_at=captured_at,
            source="backtest-test",
            run_id="backtest",
        ),
    ]


def _assert_report_invariants(report: BacktestReport, *, stake: float) -> None:
    """Every backtest report must satisfy the harness's bookkeeping laws."""
    assert report.n_bets == len(report.bets)
    assert report.n_wins + report.n_losses + report.n_unresolved == report.n_bets
    settled = report.n_wins + report.n_losses
    assert report.total_stake == pytest.approx(stake * settled)
    expected_profit = sum(b.profit for b in report.bets)
    assert report.total_profit == pytest.approx(expected_profit)
    if report.total_stake > 0:
        assert report.roi == pytest.approx(report.total_profit / report.total_stake)
    else:
        assert report.roi == 0.0
    if settled > 0:
        assert report.hit_rate == pytest.approx(report.n_wins / settled)
    else:
        assert report.hit_rate == 0.0


def test_run_backtest_hits_plus_misses_equals_nbets(tmp_path: Path) -> None:
    lake, matches = _seed_lake(tmp_path)
    report = run_backtest(
        lake,
        fixtures=matches,
        edge_threshold=0.0,
        markets=[Market.GOALS_OVER_UNDER],
        config=BACKTEST_CONFIG,
        min_history_matches=3,
        stake=1.0,
        odds_provider=_force_goals_over_provider,
    )
    _assert_report_invariants(report, stake=1.0)
    assert report.n_bets > 0, "synthetic lake must produce at least one value bet"
    assert report.n_bets == report.n_wins + report.n_losses  # no unresolved expected


def test_roi_math_matches_hand_computed_golden(tmp_path: Path) -> None:
    """ROI reproduced by hand from fixture-level realized goals.

    With ``_force_goals_over_provider`` every placed bet is OVER 0.5 at
    payout 1.20; a win pays ``1.20 * stake`` and profit is ``+0.20``, a
    loss costs ``-1.00``. Walking fixtures chronologically, a fixture
    produces a bet iff the engine accumulates enough history and the
    edge is positive — for our 10-match lake that lands on the tail of
    the season. The hand-computed ROI below doesn't pre-suppose which
    fixtures get bets; it derives the expected profit from the set of
    actually-placed bets, then checks the aggregate against the
    harness's own summary.
    """
    lake, matches = _seed_lake(tmp_path)
    stake = 10.0
    report = run_backtest(
        lake,
        fixtures=matches,
        edge_threshold=0.0,
        markets=[Market.GOALS_OVER_UNDER],
        config=BACKTEST_CONFIG,
        min_history_matches=3,
        stake=stake,
        odds_provider=_force_goals_over_provider,
    )

    expected_total_stake = 0.0
    expected_total_profit = 0.0
    for b in report.bets:
        assert b.value_bet.decimal_odds == pytest.approx(1.20)
        if b.won is True:
            expected_total_profit += stake * 1.20 - stake
            expected_total_stake += stake
            assert b.payout == pytest.approx(stake * 1.20)
            assert b.profit == pytest.approx(stake * 0.20)
        elif b.won is False:
            expected_total_profit += -stake
            expected_total_stake += stake
            assert b.payout == pytest.approx(0.0)
            assert b.profit == pytest.approx(-stake)
        else:
            # Unresolved bets contribute nothing to stake/profit totals.
            assert b.payout == pytest.approx(0.0)
            assert b.profit == pytest.approx(0.0)

    assert report.total_stake == pytest.approx(expected_total_stake)
    assert report.total_profit == pytest.approx(expected_total_profit)
    if expected_total_stake > 0:
        assert report.roi == pytest.approx(expected_total_profit / expected_total_stake)


def test_report_as_frame_has_one_row_per_bet(tmp_path: Path) -> None:
    lake, matches = _seed_lake(tmp_path)
    report = run_backtest(
        lake,
        fixtures=matches,
        edge_threshold=0.0,
        markets=[Market.GOALS_OVER_UNDER],
        config=BACKTEST_CONFIG,
        min_history_matches=3,
        stake=1.0,
        odds_provider=_force_goals_over_provider,
    )
    frame = report.as_frame()
    assert frame.height == report.n_bets
    if report.n_bets:
        assert set(frame.columns) >= {
            "match_id",
            "market",
            "selection",
            "bookmaker",
            "decimal_odds",
            "edge",
            "profit",
            "won",
        }


def test_run_backtest_empty_fixtures_returns_empty_report(tmp_path: Path) -> None:
    lake, _ = _seed_lake(tmp_path)
    report = run_backtest(
        lake,
        fixtures=[],
        edge_threshold=0.0,
        markets=[Market.GOALS_OVER_UNDER],
        config=BACKTEST_CONFIG,
        min_history_matches=3,
        stake=1.0,
        odds_provider=_force_goals_over_provider,
    )
    _assert_report_invariants(report, stake=1.0)
    assert report.n_bets == 0
    assert report.as_frame().is_empty()


def test_no_leakage_guard_suppresses_held_out_match(tmp_path: Path) -> None:
    """Constructive test: wrap the lake at the held-out fixture's date and
    confirm no row from that fixture ever surfaces through the proxy.

    This is the hard contract the phase-4a note in ``docs/knowledge.md``
    flagged for phase 4b. Anything that lets post-kickoff data leak
    into the pricing stage is a pricing-time correctness bug and must
    fail CI.
    """
    lake, matches = _seed_lake(tmp_path)
    held_out = matches[-1]

    proxy = _NoLeakageLake(lake, cutoff=held_out.match_date)

    matches_df = proxy.read_matches()
    assert held_out.match_id not in matches_df.get_column("match_id").to_list()
    assert all(d < held_out.match_date for d in matches_df.get_column("match_date").to_list())

    # Seed one odds row for the held-out fixture and confirm the proxy
    # drops it when reading.
    prov = IngestProvenance(
        source="backtest-test",
        run_id="backtest",
        actor="test",
        captured_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    snapshot = next(iter(_force_goals_over_provider(held_out)))
    lake.ingest_odds([snapshot], provenance=prov)
    odds_df = proxy.read_odds()
    assert held_out.match_id not in odds_df.get_column("match_id").to_list()


def test_no_leakage_guard_allows_prior_fixtures(tmp_path: Path) -> None:
    """The proxy must only filter out rows at or after the cutoff — earlier
    fixtures remain visible."""
    lake, matches = _seed_lake(tmp_path)
    held_out = matches[-1]
    prior = matches[0]
    proxy = _NoLeakageLake(lake, cutoff=held_out.match_date)
    matches_df = proxy.read_matches()
    assert prior.match_id in matches_df.get_column("match_id").to_list()


def test_no_leakage_guard_integrates_with_run_backtest(tmp_path: Path) -> None:
    """Enabling ``no_leakage_guard=True`` keeps the report well-formed.

    This closes the loop: the harness-level flag and the proxy must
    compose without raising or silently producing nonsensical
    aggregates.
    """
    lake, matches = _seed_lake(tmp_path)
    report = run_backtest(
        lake,
        fixtures=matches,
        edge_threshold=0.0,
        markets=[Market.GOALS_OVER_UNDER],
        config=BACKTEST_CONFIG,
        min_history_matches=3,
        stake=1.0,
        odds_provider=_force_goals_over_provider,
        no_leakage_guard=True,
    )
    _assert_report_invariants(report, stake=1.0)
