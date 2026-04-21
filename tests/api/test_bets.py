"""Stubbed bets + backtest endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_value_stub_shape(client: TestClient) -> None:
    resp = client.get("/bets/value")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["count"] == 0
    assert body["note"] == "engine not yet wired"


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


