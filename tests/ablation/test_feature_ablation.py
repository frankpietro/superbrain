"""Unit tests for :class:`FeatureAblationStudy`.

These tests exercise the greedy-forward-selection loop on a tiny
synthetic 15-match lake and assert two invariants:

1. **Determinism.** Two runs with identical inputs produce identical
   trajectories (same order of evaluated subsets, same ROI per trial,
   same best subset).
2. **Persistence contract.** The parquet dumped under
   ``data/ablation_runs/<bet>/<run_id>.parquet`` obeys
   :data:`~superbrain.ablation.ABLATION_FRAME_SCHEMA` and round-trips
   through :func:`read_ablation_runs`.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from superbrain.ablation import (
    ABLATION_FRAME_SCHEMA,
    FeatureAblationStudy,
    read_ablation_runs,
)
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
from superbrain.engine.pipeline import PricingConfig
from superbrain.engine.probability import ProbabilityConfig

ABL_SEASON = "2023-24"
ABL_LEAGUE = League.SERIE_A
ABL_TEAMS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]

ABL_CONFIG = PricingConfig(
    n_clusters=2,
    probability=ProbabilityConfig(quantile=0.3, min_matches=3),
)
FEATURE_UNIVERSE = (
    "goals",
    "goals_conceded",
    "shots",
    "corners",
    "yellow_cards",
)


def _pos(value: float) -> int:
    return max(0, round(value))


def _seed_lake(tmp_path: Path, *, seed: int = 17) -> tuple[Lake, list[Match]]:
    """15-match lake (five teams, ~1.5 round-robin) with deterministic stats."""
    rng = random.Random(seed)
    ingested = datetime(2024, 6, 1, tzinfo=UTC)
    lake = Lake(root=tmp_path / "lake")
    lake.ensure_schema()

    style = {t: rng.gauss(0.0, 1.0) for t in ABL_TEAMS}

    pairs: list[tuple[str, str]] = []
    for i, home in enumerate(ABL_TEAMS):
        for away in ABL_TEAMS[i + 1 :]:
            pairs.append((home, away))
            pairs.append((away, home))
    pairs = pairs[:15]

    day0 = date(2023, 8, 1)
    matches: list[Match] = []
    stats: list[TeamMatchStats] = []

    for idx, (home, away) in enumerate(pairs):
        match_date = day0 + timedelta(days=idx * 3)
        home_goals = rng.randint(0, 3)
        away_goals = rng.randint(0, 3)
        mid = compute_match_id(home, away, match_date, ABL_LEAGUE)
        matches.append(
            Match(
                match_id=mid,
                league=ABL_LEAGUE,
                season=ABL_SEASON,
                match_date=match_date,
                home_team=home,
                away_team=away,
                home_goals=home_goals,
                away_goals=away_goals,
                source="ablation-test",
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
                    league=ABL_LEAGUE,
                    season=ABL_SEASON,
                    match_date=match_date,
                    goals=goals,
                    goals_conceded=(away_goals if is_home else home_goals),
                    shots=_pos(11 + 2 * bias + rng.gauss(0, 2)),
                    shots_on_target=_pos(4 + bias + rng.gauss(0, 1.2)),
                    corners=_pos(5 + bias + rng.gauss(0, 1.5)),
                    yellow_cards=_pos(2 + rng.gauss(0, 1)),
                    fouls=_pos(11 + rng.gauss(0, 2)),
                    red_cards=0,
                    source="ablation-test",
                    ingested_at=ingested,
                )
            )

    prov = IngestProvenance(
        source="ablation-test",
        run_id="ablation",
        actor="test",
        captured_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    lake.ingest_matches(matches, provenance=prov)
    lake.ingest_team_match_stats(stats, provenance=prov)
    return lake, matches


def _force_goals_over_provider(fixture: Match) -> Iterable[OddsSnapshot]:
    """Emit a short-priced OVER 0.5 snapshot so every fixture yields a bet."""
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
            source="ablation-test",
            run_id="ablation",
        ),
    ]


def _build_study(lake: Lake, matches: list[Match]) -> FeatureAblationStudy:
    return FeatureAblationStudy(
        lake=lake,
        bet=Market.GOALS_OVER_UNDER,
        feature_universe=FEATURE_UNIVERSE,
        fixtures=matches,
        min_history_matches=3,
        edge_threshold=0.0,
        base_config=ABL_CONFIG,
        odds_provider=_force_goals_over_provider,
    )


def test_greedy_forward_selection_is_deterministic(tmp_path: Path) -> None:
    """Same lake + same seed + same universe => identical trajectories."""
    lake_a, matches_a = _seed_lake(tmp_path / "a", seed=17)
    lake_b, matches_b = _seed_lake(tmp_path / "b", seed=17)

    study_a = _build_study(lake_a, matches_a)
    study_b = _build_study(lake_b, matches_b)

    result_a = study_a.run(run_id="run-a", persist=True, data_root=tmp_path / "data-a")
    result_b = study_b.run(run_id="run-b", persist=True, data_root=tmp_path / "data-b")

    assert len(result_a.trajectory) == len(result_b.trajectory)
    for oa, ob in zip(result_a.trajectory, result_b.trajectory, strict=True):
        assert oa.feature_subset == ob.feature_subset
        assert oa.roi == pytest.approx(ob.roi)
        assert oa.hit_rate == pytest.approx(ob.hit_rate)
        assert oa.n_matches == ob.n_matches
        assert oa.avg_edge == pytest.approx(ob.avg_edge)

    assert result_a.best.feature_subset == result_b.best.feature_subset
    assert result_a.best.roi == pytest.approx(result_b.best.roi)


def test_best_subset_is_the_trajectory_maximum(tmp_path: Path) -> None:
    """Post-hoc: ``best`` is the trajectory's top ROI (with ties broken deterministically)."""
    lake, matches = _seed_lake(tmp_path, seed=23)
    study = _build_study(lake, matches)
    result = study.run(run_id="run-max", persist=False, data_root=tmp_path / "data")
    top_roi = max(o.roi for o in result.trajectory)
    assert result.best.roi == pytest.approx(top_roi)
    for outcome in result.trajectory:
        if outcome.roi > result.best.roi + 1e-12:
            pytest.fail(
                f"{outcome.feature_subset} has higher ROI than the chosen best "
                f"{result.best.feature_subset}"
            )


def test_parquet_persistence_roundtrips(tmp_path: Path) -> None:
    lake, matches = _seed_lake(tmp_path, seed=31)
    study = _build_study(lake, matches)

    data_root = tmp_path / "data"
    result = study.run(run_id="run-parquet", persist=True, data_root=data_root)

    assert result.parquet_path is not None
    assert result.parquet_path.exists()
    assert result.parquet_path.parent.name == Market.GOALS_OVER_UNDER.value
    assert result.parquet_path.name == "run-parquet.parquet"

    frame = pl.read_parquet(result.parquet_path)
    assert frame.height == len(result.trajectory)
    assert set(frame.columns) == set(ABLATION_FRAME_SCHEMA.names())
    for col, dtype in ABLATION_FRAME_SCHEMA.items():
        assert frame.schema[col] == dtype, f"column {col} dtype drift"

    for row, outcome in zip(frame.iter_rows(named=True), result.trajectory, strict=True):
        assert row["run_id"] == result.run_id
        assert row["bet_code"] == Market.GOALS_OVER_UNDER.value
        assert tuple(row["feature_subset"]) == outcome.feature_subset
        assert row["roi"] == pytest.approx(outcome.roi)
        assert row["hit_rate"] == pytest.approx(outcome.hit_rate)
        assert row["avg_edge"] == pytest.approx(outcome.avg_edge)
        assert row["n_matches"] == outcome.n_matches
        assert row["finished_at"] >= row["started_at"]


def test_read_ablation_runs_filters_by_bet(tmp_path: Path) -> None:
    lake, matches = _seed_lake(tmp_path, seed=41)
    study = _build_study(lake, matches)
    data_root = tmp_path / "data"
    study.run(run_id="run-read", persist=True, data_root=data_root)

    frame = read_ablation_runs(root=data_root, bet_code=Market.GOALS_OVER_UNDER.value)
    assert frame.height > 0
    assert frame["bet_code"].unique().to_list() == [Market.GOALS_OVER_UNDER.value]

    empty = read_ablation_runs(root=data_root, bet_code=Market.MATCH_1X2.value)
    assert empty.is_empty()


def test_empty_feature_universe_raises(tmp_path: Path) -> None:
    lake, matches = _seed_lake(tmp_path, seed=5)
    with pytest.raises(ValueError, match="feature universe"):
        FeatureAblationStudy(
            lake=lake,
            bet=Market.GOALS_OVER_UNDER,
            feature_universe=("goals",),
            fixtures=matches,
        ).run(persist=False)
