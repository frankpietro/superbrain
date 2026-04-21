"""Stubbed bets + backtest endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_value_stub_shape(client: TestClient, auth_header: dict[str, str]) -> None:
    resp = client.get("/bets/value", headers=auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["count"] == 0
    assert body["note"] == "engine not yet wired"


def test_markets_lists_every_registered_market(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    resp = client.get("/bets/markets", headers=auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 20
    codes = {row["code"] for row in body["items"]}
    assert "corner_total" in codes
    assert "match_1x2" in codes
    for row in body["items"]:
        assert isinstance(row["param_keys"], list)
        assert isinstance(row["selections"], list)


def test_backtest_run_returns_501(client: TestClient, auth_header: dict[str, str]) -> None:
    resp = client.post("/backtest/run", headers=auth_header)
    assert resp.status_code == 501
    assert "pending" in resp.json()["detail"]


def test_stubs_require_auth(client: TestClient) -> None:
    assert client.get("/bets/value").status_code == 401
    assert client.get("/bets/markets").status_code == 401
    assert client.post("/backtest/run").status_code == 401
