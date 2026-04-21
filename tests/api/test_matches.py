"""``/matches`` router."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from superbrain.core.models import League
from superbrain.data.connection import Lake
from tests.api.conftest import make_match, make_snapshot, provenance


def _seed_three_matches(lake: Lake) -> list[str]:
    matches = [
        make_match("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A),
        make_match("Inter", "Milan", date(2024, 9, 8), League.SERIE_A),
        make_match("Arsenal", "Chelsea", date(2024, 9, 15), League.PREMIER_LEAGUE),
    ]
    lake.ingest_matches(matches, provenance=provenance())
    return [m.match_id for m in matches]


def test_list_matches_returns_all_rows(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_three_matches(lake)
    resp = client.get("/matches", headers=auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert body["next_cursor"] is None
    dates = [row["match_date"] for row in body["items"]]
    assert dates == sorted(dates, reverse=True)


def test_matches_league_filter(client: TestClient, lake: Lake, auth_header: dict[str, str]) -> None:
    _seed_three_matches(lake)
    resp = client.get("/matches", params={"league": "premier_league"}, headers=auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["home_team"] == "Arsenal"


def test_matches_kickoff_window_filter(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_three_matches(lake)
    resp = client.get(
        "/matches",
        params={"kickoff_from": "2024-09-08", "kickoff_to": "2024-09-10"},
        headers=auth_header,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["home_team"] == "Inter"


def test_matches_limit_and_cursor(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_three_matches(lake)
    first = client.get("/matches", params={"limit": 2}, headers=auth_header).json()
    assert first["count"] == 2
    assert first["next_cursor"] == "2"
    second = client.get(
        "/matches",
        params={"limit": 2, "cursor": first["next_cursor"]},
        headers=auth_header,
    ).json()
    assert second["count"] == 1
    assert second["next_cursor"] is None


def test_match_detail_joins_latest_odds(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    ids = _seed_three_matches(lake)
    target = ids[0]
    lake.ingest_odds(
        [
            make_snapshot(match_id=target, selection="OVER", payout=1.85),
            make_snapshot(match_id=target, selection="UNDER", payout=1.95),
        ],
        provenance=provenance(),
    )
    resp = client.get(f"/matches/{target}", headers=auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert body["match_id"] == target
    assert len(body["odds"]) == 1
    group = body["odds"][0]
    assert group["market"] == "corner_total"
    assert group["bookmaker"] == "sisal"
    selections = {s["selection"] for s in group["selections"]}
    assert selections == {"OVER", "UNDER"}


def test_match_detail_404_for_unknown_id(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_three_matches(lake)
    resp = client.get("/matches/deadbeefdeadbeef", headers=auth_header)
    assert resp.status_code == 404
