"""``/matches`` router."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from superbrain.core.models import League, TeamMatchStats, compute_match_id
from superbrain.data.connection import Lake
from tests.api.conftest import make_match, make_snapshot, provenance


def _team_stats(
    *,
    match_id: str,
    team: str,
    is_home: bool,
    goals: int,
    xg: float | None,
    shots: int | None = None,
    match_date: date = date(2024, 9, 1),
    league: League = League.SERIE_A,
) -> TeamMatchStats:
    return TeamMatchStats(
        match_id=match_id,
        team=team,
        is_home=is_home,
        league=league,
        season="2024-25",
        match_date=match_date,
        goals=goals,
        shots=shots,
        xg=xg,
        source="tests",
        ingested_at=datetime(2024, 9, 1, 10, tzinfo=UTC),
    )


def _seed_three_matches(lake: Lake) -> list[str]:
    matches = [
        make_match("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A),
        make_match("Inter", "Milan", date(2024, 9, 8), League.SERIE_A),
        make_match("Arsenal", "Chelsea", date(2024, 9, 15), League.PREMIER_LEAGUE),
    ]
    lake.ingest_matches(matches, provenance=provenance())
    return [m.match_id for m in matches]


def test_list_matches_returns_all_rows(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    resp = client.get("/matches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert body["next_cursor"] is None
    dates = [row["match_date"] for row in body["items"]]
    assert dates == sorted(dates, reverse=True)


def test_matches_league_filter(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    resp = client.get("/matches", params={"league": "premier_league"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["home_team"] == "Arsenal"


def test_matches_kickoff_window_filter(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    resp = client.get(
        "/matches",
        params={"kickoff_from": "2024-09-08", "kickoff_to": "2024-09-10"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["home_team"] == "Inter"


def test_matches_date_from_date_to_aliases(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    resp = client.get(
        "/matches",
        params={"date_from": "2024-09-08", "date_to": "2024-09-10"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["home_team"] == "Inter"


def test_matches_leagues_plural_filter(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    resp = client.get(
        "/matches",
        params=[("leagues", "serie_a"), ("leagues", "premier_league")],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3


def test_matches_leagues_plural_overrides_singular(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    resp = client.get(
        "/matches",
        params=[("league", "bundesliga"), ("leagues", "premier_league")],
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [m["home_team"] for m in items] == ["Arsenal"]


def test_matches_limit_and_cursor(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    first = client.get("/matches", params={"limit": 2}).json()
    assert first["count"] == 2
    assert first["next_cursor"] == "2"
    second = client.get(
        "/matches",
        params={"limit": 2, "cursor": first["next_cursor"]},
    ).json()
    assert second["count"] == 1
    assert second["next_cursor"] is None


def test_match_detail_joins_latest_odds(client: TestClient, lake: Lake) -> None:
    ids = _seed_three_matches(lake)
    target = ids[0]
    lake.ingest_odds(
        [
            make_snapshot(match_id=target, selection="OVER", payout=1.85),
            make_snapshot(match_id=target, selection="UNDER", payout=1.95),
        ],
        provenance=provenance(),
    )
    resp = client.get(f"/matches/{target}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["match_id"] == target
    assert len(body["odds"]) == 1
    group = body["odds"][0]
    assert group["market"] == "corner_total"
    assert group["bookmaker"] == "sisal"
    selections = {s["selection"] for s in group["selections"]}
    assert selections == {"OVER", "UNDER"}


def test_match_detail_404_for_unknown_id(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    resp = client.get("/matches/deadbeefdeadbeef")
    assert resp.status_code == 404


def test_list_matches_includes_xg_when_available(client: TestClient, lake: Lake) -> None:
    ids = _seed_three_matches(lake)
    target = compute_match_id("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A)
    assert target in ids
    lake.ingest_team_match_stats(
        [
            _team_stats(match_id=target, team="Roma", is_home=True, goals=2, xg=1.7, shots=14),
            _team_stats(match_id=target, team="Lazio", is_home=False, goals=1, xg=0.9, shots=10),
        ],
        provenance=provenance(),
    )
    resp = client.get("/matches")
    assert resp.status_code == 200
    row = next(item for item in resp.json()["items"] if item["match_id"] == target)
    assert row["home_xg"] == 1.7
    assert row["away_xg"] == 0.9
    other = next(item for item in resp.json()["items"] if item["match_id"] != target)
    assert other["home_xg"] is None
    assert other["away_xg"] is None


def test_match_stats_endpoint_returns_both_teams(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    target = compute_match_id("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A)
    lake.ingest_team_match_stats(
        [
            _team_stats(match_id=target, team="Roma", is_home=True, goals=2, xg=1.7, shots=14),
            _team_stats(match_id=target, team="Lazio", is_home=False, goals=1, xg=0.9, shots=10),
        ],
        provenance=provenance(),
    )
    resp = client.get(f"/matches/{target}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["match_id"] == target
    assert body["home"]["team"] == "Roma"
    assert body["home"]["is_home"] is True
    assert body["home"]["xg"] == 1.7
    assert body["home"]["shots"] == 14
    assert body["away"]["team"] == "Lazio"
    assert body["away"]["is_home"] is False
    assert body["away"]["xg"] == 0.9


def test_match_stats_returns_null_sides_when_no_stats_yet(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    target = compute_match_id("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A)
    resp = client.get(f"/matches/{target}/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["match_id"] == target
    assert body["home"] is None
    assert body["away"] is None


def test_match_stats_404_for_unknown_match(client: TestClient, lake: Lake) -> None:
    _seed_three_matches(lake)
    resp = client.get("/matches/deadbeefdeadbeef/stats")
    assert resp.status_code == 404
