"""Bearer-token authentication."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_missing_header_returns_401(client: TestClient) -> None:
    resp = client.get("/matches")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "missing or malformed bearer token"}
    assert resp.headers.get("www-authenticate", "").lower().startswith("bearer")


def test_wrong_scheme_returns_401(client: TestClient) -> None:
    resp = client.get("/matches", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401


def test_wrong_token_returns_401(client: TestClient) -> None:
    resp = client.get("/matches", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid bearer token"}


def test_valid_token_returns_200(client: TestClient, auth_header: dict[str, str]) -> None:
    resp = client.get("/matches", headers=auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "count": 0, "next_cursor": None}


def test_second_registered_token_also_works(client: TestClient) -> None:
    resp = client.get("/matches", headers={"Authorization": "Bearer other-token"})
    assert resp.status_code == 200


def test_case_insensitive_bearer_prefix(client: TestClient) -> None:
    resp = client.get("/matches", headers={"Authorization": "bearer test-token"})
    assert resp.status_code == 200
