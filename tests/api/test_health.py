"""Public ``/health`` endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from superbrain.core.models import Bookmaker
from superbrain.data.connection import Lake
from tests.api.conftest import make_scrape_run


def test_health_is_public_and_well_shaped(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "lake_present" in body
    assert set(body["last_scrape_runs"].keys()) == {
        "sisal",
        "goldbet",
        "eurobet",
        "historical",
    }


def test_health_reflects_latest_scrape_runs(client: TestClient, lake: Lake) -> None:
    lake.log_scrape_run(
        make_scrape_run(
            run_id="s1",
            bookmaker=Bookmaker.SISAL,
            scraper="sisal.prematch",
            started_at=datetime(2024, 9, 1, 10, tzinfo=UTC),
        )
    )
    lake.log_scrape_run(
        make_scrape_run(
            run_id="s2",
            bookmaker=Bookmaker.SISAL,
            scraper="sisal.prematch",
            started_at=datetime(2024, 9, 2, 10, tzinfo=UTC),
        )
    )
    resp = client.get("/health")
    assert resp.status_code == 200
    sisal = resp.json()["last_scrape_runs"]["sisal"]
    assert sisal is not None
    assert sisal["last_status"] == "ok"
    assert sisal["last_started_at"].startswith("2024-09-02")
