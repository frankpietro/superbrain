"""``/bets/*`` endpoint smoke tests.

Integration coverage of ``GET /bets/value`` against a seeded lake lives in
``test_bets_value.py``; here we only cover the cheap read-side shape over an
empty lake, plus the markets registry.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_value_empty_lake_returns_empty_items(client: TestClient) -> None:
    resp = client.get("/bets/value")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["count"] == 0
    assert "computed_at" in body


def test_markets_lists_every_registered_market(client: TestClient) -> None:
    resp = client.get("/bets/markets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 20
    codes = {row["code"] for row in body["items"]}
    assert "corner_total" in codes
    assert "match_1x2" in codes
    for row in body["items"]:
        assert isinstance(row["param_keys"], list)
        assert isinstance(row["selections"], list)
