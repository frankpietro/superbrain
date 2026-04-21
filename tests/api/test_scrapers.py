"""``/scrapers/*`` router."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from superbrain.core.models import Bookmaker
from superbrain.data.connection import Lake
from tests.api.conftest import make_scrape_run


def _seed_runs(lake: Lake) -> None:
    now = datetime.now(tz=UTC)
    lake.log_scrape_run(
        make_scrape_run(
            run_id="r1",
            bookmaker=Bookmaker.SISAL,
            scraper="sisal.prematch",
            started_at=now - timedelta(hours=1),
            status="ok",
            rows_written=100,
        )
    )
    lake.log_scrape_run(
        make_scrape_run(
            run_id="r2",
            bookmaker=Bookmaker.SISAL,
            scraper="sisal.prematch",
            started_at=now - timedelta(hours=3),
            status="partial",
            rows_written=50,
        )
    )
    lake.log_scrape_run(
        make_scrape_run(
            run_id="r3",
            bookmaker=Bookmaker.GOLDBET,
            scraper="goldbet.prematch",
            started_at=now - timedelta(hours=2),
            status="ok",
            rows_written=200,
        )
    )


def test_runs_list_newest_first(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_runs(lake)
    resp = client.get("/scrapers/runs", headers=auth_header)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    ts = [row["started_at"] for row in items]
    assert ts == sorted(ts, reverse=True)


def test_runs_bookmaker_filter(client: TestClient, lake: Lake, auth_header: dict[str, str]) -> None:
    _seed_runs(lake)
    resp = client.get("/scrapers/runs", params={"bookmaker": "goldbet"}, headers=auth_header)
    assert resp.json()["count"] == 1


def test_status_aggregates_last_24h(
    client: TestClient, lake: Lake, auth_header: dict[str, str]
) -> None:
    _seed_runs(lake)
    resp = client.get("/scrapers/status", headers=auth_header)
    assert resp.status_code == 200
    blocks = {b["bookmaker"]: b for b in resp.json()["bookmakers"]}
    assert set(blocks.keys()) == {"sisal", "goldbet", "eurobet"}
    sisal = blocks["sisal"]
    assert sisal["last_run"] is not None
    assert sisal["last_run"]["run_id"] == "r1"
    assert sisal["runs_24h"] == 2
    assert sisal["rows_written_24h"] == 150
    assert sisal["errors_24h"] == 1
    assert blocks["eurobet"]["last_run"] is None
