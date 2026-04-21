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


def test_runs_list_newest_first(client: TestClient, lake: Lake) -> None:
    _seed_runs(lake)
    resp = client.get("/scrapers/runs")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    ts = [row["started_at"] for row in items]
    assert ts == sorted(ts, reverse=True)


def test_runs_bookmaker_filter(client: TestClient, lake: Lake) -> None:
    _seed_runs(lake)
    resp = client.get("/scrapers/runs", params={"bookmaker": "goldbet"})
    assert resp.json()["count"] == 1


def test_status_aggregates_last_24h(client: TestClient, lake: Lake) -> None:
    _seed_runs(lake)
    resp = client.get("/scrapers/status")
    assert resp.status_code == 200
    body = resp.json()
    blocks = {b["bookmaker"]: b for b in body["items"]}
    assert set(blocks.keys()) == {"sisal", "goldbet", "eurobet"}
    sisal = blocks["sisal"]
    assert sisal["last_run"] is not None
    assert sisal["last_run"]["run_id"] == "r1"
    assert sisal["runs_24h"] == 2
    assert sisal["rows_written_24h"] == 150
    assert sisal["errors_24h"] == 1
    assert sisal["healthy"] is False  # r2 was partial
    # history is newest-first, capped, and carries the compact fields the SPA renders.
    assert [h["run_id"] for h in sisal["history"]] == ["r1", "r2"]
    assert sisal["unmapped_markets_top"] == []

    goldbet = blocks["goldbet"]
    assert goldbet["last_run"]["run_id"] == "r3"
    assert goldbet["healthy"] is True
    assert goldbet["errors_24h"] == 0

    eurobet = blocks["eurobet"]
    assert eurobet["last_run"] is None
    assert eurobet["healthy"] is False
    assert eurobet["history"] == []


def test_status_normalises_success_status_to_ok(client: TestClient, lake: Lake) -> None:
    """Real scrapers write ``status='success'``; the API must emit ``'ok'``.

    Without normalisation the SPA's badge logic (``status === 'ok'``) would
    falsely flag every healthy run as an error.
    """
    now = datetime.now(tz=UTC)
    lake.log_scrape_run(
        make_scrape_run(
            run_id="s1",
            bookmaker=Bookmaker.SISAL,
            scraper="sisal.prematch",
            started_at=now - timedelta(minutes=5),
            status="success",
            rows_written=10_000,
        )
    )
    resp = client.get("/scrapers/status")
    assert resp.status_code == 200
    sisal = next(b for b in resp.json()["items"] if b["bookmaker"] == "sisal")
    assert sisal["last_run"]["status"] == "ok"
    assert sisal["healthy"] is True
    assert sisal["errors_24h"] == 0
    assert sisal["history"][0]["status"] == "ok"

    runs = client.get("/scrapers/runs", params={"bookmaker": "sisal"}).json()["items"]
    assert runs[0]["status"] == "ok"
