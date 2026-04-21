"""``GET /bets/value`` — integration test against a synthetic lake.

Builds enough history for the engine to cluster, then inserts a single
future fixture with generous OVER 0.5 odds. The endpoint must surface at
least one priced value bet.
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from superbrain.api.app import create_app
from superbrain.api.config import Settings
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

TEAMS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]


def _pos(value: float) -> int:
    return max(0, round(value))


def _seed_lake_with_future(root: Path, *, seed: int = 17) -> Lake:
    """Seed enough history + a future fixture to trigger pricing."""
    rng = random.Random(seed)
    ingested = datetime(2024, 6, 1, tzinfo=UTC)
    lake = Lake(root=root / "lake")
    lake.ensure_schema()

    style = {t: rng.gauss(0.0, 1.0) for t in TEAMS}
    pairs: list[tuple[str, str]] = []
    for i, home in enumerate(TEAMS):
        for away in TEAMS[i + 1 :]:
            pairs.append((home, away))
            pairs.append((away, home))

    day0 = date(2023, 8, 1)
    matches: list[Match] = []
    stats: list[TeamMatchStats] = []
    for idx, (home, away) in enumerate(pairs):
        match_date = day0 + timedelta(days=idx * 3)
        home_goals = rng.randint(1, 3)
        away_goals = rng.randint(0, 2)
        mid = compute_match_id(home, away, match_date, League.SERIE_A)
        matches.append(
            Match(
                match_id=mid,
                league=League.SERIE_A,
                season="2023-24",
                match_date=match_date,
                home_team=home,
                away_team=away,
                home_goals=home_goals,
                away_goals=away_goals,
                source="api-test",
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
                    league=League.SERIE_A,
                    season="2023-24",
                    match_date=match_date,
                    goals=goals,
                    goals_conceded=(away_goals if is_home else home_goals),
                    shots=_pos(11 + 2 * bias + rng.gauss(0, 2)),
                    shots_on_target=_pos(4 + bias + rng.gauss(0, 1.2)),
                    corners=_pos(5 + bias + rng.gauss(0, 1.5)),
                    yellow_cards=_pos(2 + rng.gauss(0, 1)),
                    fouls=_pos(11 + rng.gauss(0, 2)),
                    red_cards=0,
                    source="api-test",
                    ingested_at=ingested,
                )
            )

    future_date = date.today() + timedelta(days=5)
    future_home, future_away = TEAMS[0], TEAMS[1]
    future_mid = compute_match_id(future_home, future_away, future_date, League.SERIE_A)
    matches.append(
        Match(
            match_id=future_mid,
            league=League.SERIE_A,
            season="2023-24",
            match_date=future_date,
            home_team=future_home,
            away_team=future_away,
            home_goals=None,
            away_goals=None,
            source="api-test",
            ingested_at=ingested,
        )
    )

    snapshots = [
        OddsSnapshot(
            bookmaker=Bookmaker.SISAL,
            bookmaker_event_id=f"evt-{future_mid}",
            match_id=future_mid,
            match_label=f"{future_home}-{future_away}",
            match_date=future_date,
            season="2023-24",
            league=League.SERIE_A,
            home_team=future_home,
            away_team=future_away,
            market=Market.GOALS_OVER_UNDER,
            market_params={"threshold": 0.5},
            selection=selection,
            payout=payout,
            captured_at=datetime.now(UTC) - timedelta(hours=1),
            source="api-test",
            run_id="bets-value-api",
        )
        for selection, payout in (("OVER", 1.20), ("UNDER", 3.50))
    ]

    prov = IngestProvenance(
        source="api-test",
        run_id="bets-value-api",
        actor="test",
        captured_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    lake.ingest_matches(matches, provenance=prov)
    lake.ingest_team_match_stats(stats, provenance=prov)
    lake.ingest_odds(snapshots, provenance=prov)
    return lake


@pytest.fixture()
def seeded_app_with_future(tmp_path: Path) -> FastAPI:
    lake = _seed_lake_with_future(tmp_path)
    settings = Settings(
        SUPERBRAIN_LAKE_PATH=tmp_path / "lake",
        SUPERBRAIN_API_TOKENS=("test-token",),
        SUPERBRAIN_CORS_ORIGINS=("http://localhost:5273",),
        SUPERBRAIN_LOG_LEVEL="WARNING",
    )
    return create_app(settings=settings, lake=lake)


TUNING = "min_edge=0.0&n_clusters=2&quantile=0.3&min_matches=3&min_history_matches=3"


def test_value_surfaces_bet_when_history_sufficient(
    seeded_app_with_future: FastAPI,
) -> None:
    with TestClient(seeded_app_with_future, raise_server_exceptions=False) as client:
        resp = client.get(
            f"/bets/value?{TUNING}",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    top = body["items"][0]
    assert top["market"] == "goals_over_under"
    assert top["selection"] in {"OVER", "UNDER"}
    assert 0.0 <= top["book_prob"] <= 1.0
    assert 0.0 <= top["model_prob"] <= 1.0
    assert top["edge"] > 0.0
    assert top["sample_size"] > 0


def test_value_respects_min_edge_filter(seeded_app_with_future: FastAPI) -> None:
    with TestClient(seeded_app_with_future, raise_server_exceptions=False) as client:
        resp = client.get(
            "/bets/value?min_edge=0.95&n_clusters=2&quantile=0.3&min_matches=3&min_history_matches=3",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0


def test_value_respects_market_filter(seeded_app_with_future: FastAPI) -> None:
    with TestClient(seeded_app_with_future, raise_server_exceptions=False) as client:
        resp = client.get(
            f"/bets/value?markets=cards_total&{TUNING}",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
