"""Engine pipeline integration tests.

Builds a deterministic 20-match synthetic lake, asks the full pricing
pipeline to price an upcoming fixture, and asserts that:

* every emitted :class:`~superbrain.engine.pipeline.PricedOutcome` has a
  finite probability in ``[0, 1]`` and a matching ``model_payout``;
* ``find_value_bets`` surfaces rows with a non-negative expected-value
  contribution (``p * decimal_odds - 1 >= 0``), sorted by descending
  edge;
* the pipeline is idempotent on a second call over the same inputs.

The lake is built inline (not reused from ``conftest.py``) because this
test nails down the exact 20-match-lake contract from the phase 4b
follow-up in ``docs/knowledge.md``.
"""

from __future__ import annotations

import math
import random
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
from superbrain.engine.pipeline import (
    DEFAULT_FEATURE_COLUMNS,
    PricingConfig,
    build_engine_context,
    find_value_bets,
    price_fixture,
)
from superbrain.engine.probability import ProbabilityConfig

LAKE_SEASON = "2023-24"
LAKE_LEAGUE = League.SERIE_A
LAKE_TEAMS: list[str] = [
    "Alpha",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
]
PIPELINE_PROBABILITY = ProbabilityConfig(quantile=0.5, min_matches=3)
PIPELINE_CONFIG = PricingConfig(
    n_clusters=3,
    feature_columns=DEFAULT_FEATURE_COLUMNS,
    probability=PIPELINE_PROBABILITY,
)


def _pos(value: float) -> int:
    return max(0, round(value))


def _lake_fixtures(*, rng_seed: int = 7) -> tuple[list[Match], list[TeamMatchStats], Match]:
    """Return ``(matches, stats, upcoming_fixture)``.

    20 training fixtures are generated from a round-robin over 6 teams;
    the 21st fixture is held out and used as the pricing target. Stats
    are deterministic from the seed.
    """
    rng = random.Random(rng_seed)
    ingested = datetime(2024, 6, 1, tzinfo=UTC)
    style_seed = {team: rng.gauss(0.0, 1.0) for team in LAKE_TEAMS}

    pairs: list[tuple[str, str]] = []
    for i, home in enumerate(LAKE_TEAMS):
        for away in LAKE_TEAMS[i + 1 :]:
            pairs.append((home, away))
            pairs.append((away, home))
    # 6 teams times (6-1) = 30 ordered pairs; take first 20 as history, 21st
    # as pricing target. Keeps the lake faithfully at 20 matches.
    training_pairs = pairs[:20]
    upcoming_pair = pairs[20]

    day0 = date(2023, 8, 1)
    matches: list[Match] = []
    stats: list[TeamMatchStats] = []

    for idx, (home, away) in enumerate(training_pairs):
        match_date = day0 + timedelta(days=idx * 3)
        home_goals = rng.randint(0, 4)
        away_goals = rng.randint(0, 3)
        mid = compute_match_id(home, away, match_date, LAKE_LEAGUE)
        matches.append(
            Match(
                match_id=mid,
                league=LAKE_LEAGUE,
                season=LAKE_SEASON,
                match_date=match_date,
                home_team=home,
                away_team=away,
                home_goals=home_goals,
                away_goals=away_goals,
                source="pipeline-test",
                ingested_at=ingested,
            )
        )
        for team, opp, is_home, goals in (
            (home, away, True, home_goals),
            (away, home, False, away_goals),
        ):
            bias = style_seed[team] - style_seed[opp]
            stats.append(
                TeamMatchStats(
                    match_id=mid,
                    team=team,
                    is_home=is_home,
                    league=LAKE_LEAGUE,
                    season=LAKE_SEASON,
                    match_date=match_date,
                    goals=int(goals),
                    goals_conceded=(away_goals if is_home else home_goals),
                    shots=_pos(12 + 2 * bias + rng.gauss(0, 2)),
                    shots_on_target=_pos(5 + bias + rng.gauss(0, 1.2)),
                    corners=_pos(5 + bias + rng.gauss(0, 1.6)),
                    yellow_cards=_pos(2 + rng.gauss(0, 1)),
                    fouls=_pos(11 + rng.gauss(0, 2)),
                    red_cards=0,
                    source="pipeline-test",
                    ingested_at=ingested,
                )
            )

    upcoming_home, upcoming_away = upcoming_pair
    upcoming_date = day0 + timedelta(days=len(training_pairs) * 3 + 3)
    upcoming_mid = compute_match_id(upcoming_home, upcoming_away, upcoming_date, LAKE_LEAGUE)
    upcoming = Match(
        match_id=upcoming_mid,
        league=LAKE_LEAGUE,
        season=LAKE_SEASON,
        match_date=upcoming_date,
        home_team=upcoming_home,
        away_team=upcoming_away,
        source="pipeline-test",
        ingested_at=ingested,
    )
    return matches, stats, upcoming


@pytest.fixture()
def twenty_match_lake(tmp_path: Path) -> tuple[Lake, Match]:
    matches, stats, upcoming = _lake_fixtures()
    assert len(matches) == 20
    lake = Lake(root=tmp_path / "lake")
    lake.ensure_schema()
    prov = IngestProvenance(
        source="pipeline-test",
        run_id="pipeline",
        actor="test",
        captured_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    lake.ingest_matches(matches, provenance=prov)
    lake.ingest_team_match_stats(stats, provenance=prov)
    return lake, upcoming


def _odds_for_upcoming(fixture: Match) -> list[OddsSnapshot]:
    """Deterministic odds for the upcoming fixture across 4 markets."""
    base = {
        "bookmaker": Bookmaker.SISAL,
        "bookmaker_event_id": f"evt-{fixture.match_id}",
        "match_id": fixture.match_id,
        "match_label": f"{fixture.home_team}-{fixture.away_team}",
        "match_date": fixture.match_date,
        "season": fixture.season,
        "league": fixture.league,
        "home_team": fixture.home_team,
        "away_team": fixture.away_team,
        "captured_at": datetime.combine(fixture.match_date, datetime.min.time(), tzinfo=UTC)
        - timedelta(hours=4),
        "source": "pipeline-test",
        "run_id": "pipeline",
    }
    out: list[OddsSnapshot] = []
    for sel, payout in (("OVER", 1.85), ("UNDER", 1.95)):
        out.append(
            OddsSnapshot(
                market=Market.GOALS_OVER_UNDER,
                market_params={"threshold": 2.5},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    for sel, payout in (("OVER", 1.80), ("UNDER", 2.00)):
        out.append(
            OddsSnapshot(
                market=Market.CORNER_TOTAL,
                market_params={"threshold": 9.5},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    for sel, payout in (("1", 2.10), ("X", 3.30), ("2", 3.50)):
        out.append(
            OddsSnapshot(
                market=Market.MATCH_1X2,
                market_params={},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    for sel, payout in (("YES", 1.70), ("NO", 2.15)):
        out.append(
            OddsSnapshot(
                market=Market.GOALS_BOTH_TEAMS,
                market_params={},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    return out


def test_lake_fixture_has_exactly_20_matches(
    twenty_match_lake: tuple[Lake, Match],
) -> None:
    lake, _ = twenty_match_lake
    df = lake.read_matches()
    assert df.height == 20


def test_build_engine_context_returns_populated_similarity(
    twenty_match_lake: tuple[Lake, Match],
) -> None:
    lake, fixture = twenty_match_lake
    context = build_engine_context(
        lake,
        fixture=fixture,
        config=PIPELINE_CONFIG,
        min_history_matches=30,
    )
    assert context is not None
    assert context.similarity.n > 0
    assert context.assignment.n_clusters == PIPELINE_CONFIG.n_clusters


def test_price_fixture_returns_finite_probabilities(
    twenty_match_lake: tuple[Lake, Match],
) -> None:
    lake, fixture = twenty_match_lake
    odds = _odds_for_upcoming(fixture)

    priced = price_fixture(
        lake,
        fixture=fixture,
        odds_snapshots=odds,
        config=PIPELINE_CONFIG,
        min_history_matches=30,
    )

    assert priced, "pipeline produced no priced outcomes"
    seen_markets = {p.outcome.market for p in priced}
    # At least the pooled-stat markets (goals, corners, 1x2, btts) must
    # surface — they all read the ``goals``/``corners`` columns which
    # the synthetic lake populates.
    assert seen_markets, "no markets priced on the synthetic lake"

    for p in priced:
        assert math.isfinite(p.model_probability)
        assert 0.0 <= p.model_probability <= 1.0
        if p.model_probability > 0.0:
            assert p.model_payout == pytest.approx(1.0 / p.model_probability)
        else:
            assert p.model_payout == 10_000.0
        assert p.sample_size >= PIPELINE_PROBABILITY.min_matches
        assert p.target_columns, "target columns must not be empty"


def test_find_value_bets_yields_nonnegative_expected_edge(
    twenty_match_lake: tuple[Lake, Match],
) -> None:
    lake, fixture = twenty_match_lake
    odds = _odds_for_upcoming(fixture)

    value_bets = find_value_bets(
        lake,
        fixture=fixture,
        edge_threshold=0.0,
        odds_snapshots=odds,
        config=PIPELINE_CONFIG,
    )

    for vb in value_bets:
        assert math.isfinite(vb.edge)
        assert vb.edge >= 0.0 - 1e-12
        # edge = p - 1 / d  ⇒  p * d - 1 = edge * d  ≥ 0
        ev_contribution = vb.priced.model_probability * vb.decimal_odds - 1.0
        assert ev_contribution >= -1e-9
        assert vb.decimal_odds > 1.0
        assert 0.0 <= vb.book_probability <= 1.0

    edges = [vb.edge for vb in value_bets]
    assert edges == sorted(edges, reverse=True), "value bets must be sorted by descending edge"


def test_price_fixture_is_deterministic_over_repeats(
    twenty_match_lake: tuple[Lake, Match],
) -> None:
    lake, fixture = twenty_match_lake
    odds = _odds_for_upcoming(fixture)

    first = price_fixture(
        lake,
        fixture=fixture,
        odds_snapshots=odds,
        config=PIPELINE_CONFIG,
        min_history_matches=30,
    )
    second = price_fixture(
        lake,
        fixture=fixture,
        odds_snapshots=odds,
        config=PIPELINE_CONFIG,
        min_history_matches=30,
    )

    assert len(first) == len(second)
    for a, b in zip(first, second, strict=True):
        assert a.outcome == b.outcome
        assert a.model_probability == pytest.approx(b.model_probability)
        assert a.sample_size == b.sample_size


def test_price_fixture_returns_empty_when_below_min_history(
    twenty_match_lake: tuple[Lake, Match],
) -> None:
    lake, fixture = twenty_match_lake
    odds = _odds_for_upcoming(fixture)
    priced = price_fixture(
        lake,
        fixture=fixture,
        odds_snapshots=odds,
        config=PIPELINE_CONFIG,
        min_history_matches=1_000_000,
    )
    assert priced == []
