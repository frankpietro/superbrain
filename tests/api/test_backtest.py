"""Integration tests for the wired ``POST /backtest/run`` endpoint.

Seeds a small synthetic lake (matches + team stats + odds) and asserts
that the API:

1. Rejects unknown leagues / markets with 400.
2. Returns a well-formed :class:`BacktestRunResponse` on empty lakes.
3. Produces a valid report with ``n_wins + n_losses + n_unresolved == n_bets``
   on a seeded lake, and bet rows shaped as the SPA expects.
4. Filters by ``threshold`` when provided (best-effort on markets that
   carry a ``threshold`` param).
"""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

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

TEAMS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
SEASON = "2023-24"
LEAGUE = League.SERIE_A


def _seed_backtest_lake(lake: Lake) -> list[Match]:
    """Seed lake with 10 matches, 20 stats rows, and O/U odds on each fixture."""
    rng = random.Random(13)
    ingested = datetime(2024, 6, 1, tzinfo=UTC)
    style = {t: rng.gauss(0, 1) for t in TEAMS}

    pairs: list[tuple[str, str]] = []
    for i, home in enumerate(TEAMS):
        for away in TEAMS[i + 1 :]:
            pairs.append((home, away))
            pairs.append((away, home))
    pairs = pairs[:10]

    day0 = date(2023, 8, 1)
    matches: list[Match] = []
    stats: list[TeamMatchStats] = []
    snaps: list[OddsSnapshot] = []

    for idx, (home, away) in enumerate(pairs):
        match_date = day0 + timedelta(days=idx * 3)
        home_goals = rng.randint(0, 3)
        away_goals = rng.randint(0, 3)
        mid = compute_match_id(home, away, match_date, LEAGUE)
        matches.append(
            Match(
                match_id=mid,
                league=LEAGUE,
                season=SEASON,
                match_date=match_date,
                home_team=home,
                away_team=away,
                home_goals=home_goals,
                away_goals=away_goals,
                source="api-backtest-test",
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
                    league=LEAGUE,
                    season=SEASON,
                    match_date=match_date,
                    goals=goals,
                    goals_conceded=(away_goals if is_home else home_goals),
                    shots=max(0, round(11 + 2 * bias + rng.gauss(0, 2))),
                    shots_on_target=max(0, round(4 + bias + rng.gauss(0, 1.2))),
                    corners=max(0, round(5 + bias + rng.gauss(0, 1.5))),
                    yellow_cards=max(0, round(2 + rng.gauss(0, 1))),
                    fouls=max(0, round(11 + rng.gauss(0, 2))),
                    red_cards=0,
                    source="api-backtest-test",
                    ingested_at=ingested,
                )
            )
        captured_at = datetime.combine(match_date, datetime.min.time(), tzinfo=UTC) - timedelta(
            hours=3
        )
        for sel, payout in (("OVER", 1.20), ("UNDER", 4.80)):
            snaps.append(
                OddsSnapshot(
                    bookmaker=Bookmaker.SISAL,
                    bookmaker_event_id=f"evt-{mid}",
                    match_id=mid,
                    match_label=f"{home}-{away}",
                    match_date=match_date,
                    season=SEASON,
                    league=LEAGUE,
                    home_team=home,
                    away_team=away,
                    market=Market.GOALS_OVER_UNDER,
                    market_params={"threshold": 0.5},
                    selection=sel,
                    payout=payout,
                    captured_at=captured_at,
                    source="api-backtest-test",
                    run_id="api-backtest-test",
                )
            )

    prov = IngestProvenance(
        source="api-backtest-test",
        run_id="api-backtest-test",
        actor="test",
        captured_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    lake.ingest_matches(matches, provenance=prov)
    lake.ingest_team_match_stats(stats, provenance=prov)
    lake.ingest_odds(snaps, provenance=prov)
    return matches


def test_backtest_requires_auth(client: TestClient) -> None:
    resp = client.post("/backtest/run", json={"league": "serie_a", "season": "2023-24"})
    assert resp.status_code == 401


def test_backtest_rejects_unknown_league(client: TestClient, auth_header: dict[str, str]) -> None:
    resp = client.post(
        "/backtest/run",
        headers=auth_header,
        json={"league": "not_a_league", "season": "2023-24"},
    )
    assert resp.status_code == 400
    assert "unknown league" in resp.json()["detail"]


def test_backtest_rejects_unknown_market(client: TestClient, auth_header: dict[str, str]) -> None:
    resp = client.post(
        "/backtest/run",
        headers=auth_header,
        json={"league": "serie_a", "season": "2023-24", "market": "zzz"},
    )
    assert resp.status_code == 400
    assert "unknown market" in resp.json()["detail"]


def test_backtest_on_empty_lake_returns_zero_bets(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    resp = client.post(
        "/backtest/run",
        headers=auth_header,
        json={"league": "serie_a", "season": "2023-24"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fixtures_considered"] == 0
    assert body["summary"]["n_bets"] == 0
    assert body["bets"] == []
    assert body["summary"]["roi"] == 0.0
    assert body["summary"]["hit_rate"] == 0.0


def test_backtest_on_seeded_lake_returns_wellformed_report(
    client: TestClient, auth_header: dict[str, str], lake: Lake
) -> None:
    matches = _seed_backtest_lake(lake)
    resp = client.post(
        "/backtest/run",
        headers=auth_header,
        json={
            "league": "serie_a",
            "season": "2023-24",
            "market": "goals_over_under",
            "edge_cutoff": 0.0,
            "stake": 10.0,
            "min_history_matches": 3,
            "n_clusters": 2,
        },
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["fixtures_considered"] == len(matches)

    summary = body["summary"]
    assert summary["n_wins"] + summary["n_losses"] + summary["n_unresolved"] == summary["n_bets"]
    if summary["total_stake"] > 0:
        assert abs(summary["roi"] - summary["total_profit"] / summary["total_stake"]) < 1e-9

    assert len(body["bets"]) == summary["n_bets"]
    for bet in body["bets"]:
        assert bet["market"] == "goals_over_under"
        assert bet["bookmaker"] == "sisal"
        assert 0.0 <= bet["model_probability"] <= 1.0
        assert bet["decimal_odds"] > 1.0
        assert bet["stake"] == 10.0


def test_backtest_with_too_many_clusters_returns_400(
    client: TestClient, auth_header: dict[str, str], lake: Lake
) -> None:
    """Default n_clusters=8 on a 5-team synthetic lake must 400, not 500.

    Guards the phase-10 graceful-failure contract: clustering errors should
    surface as a friendly 4xx so the SPA can render them, not leak as
    generic 500s.
    """
    _seed_backtest_lake(lake)
    resp = client.post(
        "/backtest/run",
        headers=auth_header,
        json={
            "league": "serie_a",
            "season": "2023-24",
            "market": "goals_over_under",
            "edge_cutoff": 0.0,
            "min_history_matches": 3,
        },
    )
    assert resp.status_code == 400
    assert "n_clusters" in resp.json()["detail"]


def test_backtest_threshold_filters_best_effort(
    client: TestClient, auth_header: dict[str, str], lake: Lake
) -> None:
    _seed_backtest_lake(lake)
    resp = client.post(
        "/backtest/run",
        headers=auth_header,
        json={
            "league": "serie_a",
            "season": "2023-24",
            "market": "goals_over_under",
            "edge_cutoff": 0.0,
            "threshold": 99.5,  # no seeded odds match this line
            "min_history_matches": 3,
            "n_clusters": 2,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["n_bets"] == 0
    assert body["bets"] == []
