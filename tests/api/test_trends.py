"""``/trends`` router."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League
from superbrain.data.connection import Lake
from tests.api.conftest import make_snapshot, provenance


def _now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def _seed_variability(lake: Lake) -> datetime:
    """Seed two series with different volatility and one stable series."""
    now = _now()
    kickoff = (now + timedelta(hours=36)).date()
    snapshots = [
        # Series 1: Sisal CORNER_TOTAL OVER — oscillating (high CV).
        make_snapshot(
            bookmaker=Bookmaker.SISAL,
            bookmaker_event_id="evt-corner",
            market=Market.CORNER_TOTAL,
            selection="OVER",
            captured_at=now - timedelta(hours=24),
            match_date=kickoff,
            payout=1.70,
        ),
        make_snapshot(
            bookmaker=Bookmaker.SISAL,
            bookmaker_event_id="evt-corner",
            market=Market.CORNER_TOTAL,
            selection="OVER",
            captured_at=now - timedelta(hours=12),
            match_date=kickoff,
            payout=2.10,
        ),
        make_snapshot(
            bookmaker=Bookmaker.SISAL,
            bookmaker_event_id="evt-corner",
            market=Market.CORNER_TOTAL,
            selection="OVER",
            captured_at=now - timedelta(hours=3),
            match_date=kickoff,
            payout=1.60,
        ),
        # Series 2: Goldbet MATCH_1X2 "1" — stable (low CV).
        make_snapshot(
            bookmaker=Bookmaker.GOLDBET,
            bookmaker_event_id="gb-match",
            market=Market.MATCH_1X2,
            market_params={},
            selection="1",
            captured_at=now - timedelta(hours=24),
            match_date=kickoff,
            payout=2.10,
            source="goldbet-test",
            league=League.SERIE_A,
        ),
        make_snapshot(
            bookmaker=Bookmaker.GOLDBET,
            bookmaker_event_id="gb-match",
            market=Market.MATCH_1X2,
            market_params={},
            selection="1",
            captured_at=now - timedelta(hours=12),
            match_date=kickoff,
            payout=2.11,
            source="goldbet-test",
            league=League.SERIE_A,
        ),
        make_snapshot(
            bookmaker=Bookmaker.GOLDBET,
            bookmaker_event_id="gb-match",
            market=Market.MATCH_1X2,
            market_params={},
            selection="1",
            captured_at=now - timedelta(hours=3),
            match_date=kickoff,
            payout=2.09,
            source="goldbet-test",
            league=League.SERIE_A,
        ),
    ]
    lake.ingest_odds(snapshots, provenance=provenance())
    return now


def test_variability_by_market_sorts_desc_by_cv(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_variability(lake)
    resp = client.get(
        "/trends/variability",
        params={"group_by": "market", "min_points": 3, "since_hours": 168},
        headers=auth_header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["group_by"] == "market"
    items = body["items"]
    assert len(items) == 2
    codes = [it["key"] for it in items]
    assert codes[0] == Market.CORNER_TOTAL.value
    assert codes[1] == Market.MATCH_1X2.value
    assert items[0]["avg_cv_pct"] > items[1]["avg_cv_pct"]
    assert items[0]["series_count"] == 1
    assert items[0]["observation_count"] == 3


def test_variability_by_team_counts_home_and_away(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_variability(lake)
    resp = client.get(
        "/trends/variability",
        params={"group_by": "team", "min_points": 3, "since_hours": 168},
        headers=auth_header,
    )
    assert resp.status_code == 200
    teams = {it["key"]: it for it in resp.json()["items"]}
    assert {"Roma", "Lazio"} <= set(teams.keys())
    assert teams["Roma"]["series_count"] == 2
    assert teams["Roma"]["observation_count"] == 6


def test_variability_by_match_collapses_all_series(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_variability(lake)
    resp = client.get(
        "/trends/variability",
        params={"group_by": "match", "min_points": 3, "since_hours": 168},
        headers=auth_header,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["series_count"] == 2
    assert items[0]["observation_count"] == 6


def test_variability_bookmaker_filter(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_variability(lake)
    resp = client.get(
        "/trends/variability",
        params={"group_by": "market", "bookmaker": "goldbet", "since_hours": 168, "min_points": 3},
        headers=auth_header,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {it["key"] for it in items} == {Market.MATCH_1X2.value}


def test_variability_rejects_bad_group_by(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    resp = client.get(
        "/trends/variability",
        params={"group_by": "bookmaker"},
        headers=auth_header,
    )
    assert resp.status_code == 400


def test_variability_empty_lake_returns_empty_items(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    resp = client.get(
        "/trends/variability", params={"group_by": "market"}, headers=auth_header
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total_series"] == 0


def test_time_to_kickoff_groups_transitions(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_variability(lake)
    resp = client.get(
        "/trends/time-to-kickoff",
        params={"bucket_hours": 12, "since_hours": 168, "min_points": 3},
        headers=auth_header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket_hours"] == 12
    assert body["total_transitions"] == 4
    buckets = body["buckets"]
    assert len(buckets) >= 1
    for b in buckets:
        assert b["hours_max"] == b["hours_min"] + 12
        assert 0.0 <= b["prob_any_change"] <= 1.0


def test_time_to_kickoff_market_filter(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_variability(lake)
    resp = client.get(
        "/trends/time-to-kickoff",
        params={"bucket_hours": 6, "market": "match_1x2", "since_hours": 168, "min_points": 3},
        headers=auth_header,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_transitions"] == 2


def test_time_to_kickoff_empty_lake(client: TestClient, auth_header: dict[str, str]) -> None:
    resp = client.get("/trends/time-to-kickoff", headers=auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_transitions"] == 0
    assert body["buckets"] == []


def test_trends_requires_auth(client: TestClient) -> None:
    assert client.get("/trends/variability").status_code == 401
    assert client.get("/trends/time-to-kickoff").status_code == 401


def test_time_to_kickoff_drops_post_kickoff_transitions(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    now = _now()
    past_kickoff = (now - timedelta(days=2)).date()
    snapshots = [
        make_snapshot(
            bookmaker=Bookmaker.SISAL,
            bookmaker_event_id="evt-past",
            market=Market.CORNER_TOTAL,
            selection="OVER",
            captured_at=now - timedelta(hours=3),
            match_date=past_kickoff,
            payout=1.85,
        ),
        make_snapshot(
            bookmaker=Bookmaker.SISAL,
            bookmaker_event_id="evt-past",
            market=Market.CORNER_TOTAL,
            selection="OVER",
            captured_at=now - timedelta(hours=1),
            match_date=past_kickoff,
            payout=1.95,
        ),
        make_snapshot(
            bookmaker=Bookmaker.SISAL,
            bookmaker_event_id="evt-past",
            market=Market.CORNER_TOTAL,
            selection="OVER",
            captured_at=now,
            match_date=past_kickoff,
            payout=2.00,
        ),
    ]
    lake.ingest_odds(snapshots, provenance=provenance())
    resp = client.get(
        "/trends/time-to-kickoff",
        params={"since_hours": 168, "min_points": 3},
        headers=auth_header,
    )
    assert resp.status_code == 200
    assert resp.json()["total_transitions"] == 0
    _ = date(2024, 9, 1)
