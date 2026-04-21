"""``/odds`` router."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League
from superbrain.data.connection import Lake
from tests.api.conftest import make_snapshot, provenance


def _seed_odds(lake: Lake) -> None:
    snapshots = [
        make_snapshot(
            bookmaker=Bookmaker.SISAL,
            market=Market.CORNER_TOTAL,
            selection="OVER",
            captured_at=datetime(2024, 9, 1, 10, tzinfo=UTC),
            payout=1.85,
        ),
        make_snapshot(
            bookmaker=Bookmaker.SISAL,
            market=Market.CORNER_TOTAL,
            selection="OVER",
            captured_at=datetime(2024, 9, 1, 12, tzinfo=UTC),
            payout=1.90,
        ),
        make_snapshot(
            bookmaker=Bookmaker.GOLDBET,
            bookmaker_event_id="gb-1",
            market=Market.MATCH_1X2,
            market_params={},
            selection="1",
            captured_at=datetime(2024, 9, 1, 11, tzinfo=UTC),
            payout=2.10,
            source="goldbet-test",
            league=League.SERIE_A,
        ),
    ]
    lake.ingest_odds(snapshots, provenance=provenance())


def test_list_odds_default_order(client: TestClient, lake: Lake) -> None:
    _seed_odds(lake)
    resp = client.get("/odds")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    captured = [row["captured_at"] for row in items]
    assert captured == sorted(captured, reverse=True)


def test_odds_bookmaker_filter(client: TestClient, lake: Lake) -> None:
    _seed_odds(lake)
    resp = client.get("/odds", params={"bookmaker": "goldbet"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["market"] == "match_1x2"


def test_odds_market_and_captured_from(client: TestClient, lake: Lake) -> None:
    _seed_odds(lake)
    resp = client.get(
        "/odds",
        params={"market": "corner_total", "captured_from": "2024-09-01T11:00:00Z"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["payout"] == 1.90


def test_odds_limit_rejects_over_cap(client: TestClient, lake: Lake) -> None:
    _seed_odds(lake)
    resp = client.get("/odds", params={"limit": 10000})
    assert resp.status_code == 422


def test_odds_match_id_filter_respects_date(client: TestClient, lake: Lake) -> None:
    _seed_odds(lake)
    resp = client.get("/odds", params={"match_id": "none-match"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
    _ = date(2024, 9, 1)
