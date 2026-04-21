"""End-to-end tests for :func:`superbrain.scrapers.bookmakers.eurobet.scrape`.

Both transports are stubbed:

* ``respx`` mocks the public ``httpx`` endpoints (top-disciplines).
* A fake curl_cffi session returns pre-canned payloads for every
  meeting / event request, so the orchestrator exercises the full
  discovery + markets + ingest path without hitting the network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from superbrain.core.models import Bookmaker, League
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.eurobet.client import EUROBET_BASE, EurobetClient
from superbrain.scrapers.bookmakers.eurobet.scraper import scrape

FIXTURES = Path(__file__).parent.parent.parent.parent / "fixtures" / "bookmakers" / "eurobet"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


class _FakeCFFIResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body
        raw = json.dumps(body)
        self.status_code = 200
        self.text = raw

    def json(self) -> Any:
        return self._body


class _RoutingCFFISession:
    """Fake async curl_cffi session that routes by URL substring."""

    def __init__(self, routes: dict[str, dict[str, Any]]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    async def get(self, url: str, **_: Any) -> _FakeCFFIResponse:
        self.calls.append(url)
        for pattern, body in self._routes.items():
            if pattern in url:
                return _FakeCFFIResponse(body)
        raise AssertionError(f"no fake route for url {url}")

    async def close(self) -> None:
        return None


@pytest.fixture
def lake(tmp_path: Path) -> Lake:
    lk = Lake(root=tmp_path / "lake")
    lk.ensure_schema()
    return lk


@pytest.fixture
def top_disciplines_payload() -> dict[str, Any]:
    return _load("top_disciplines_calcio.json")


@pytest.fixture
def meeting_payload() -> dict[str, Any]:
    return _load("meeting_serie_a.json")


@pytest.fixture
def event_payload() -> dict[str, Any]:
    return _load("event_napoli_cremonese.json")


@pytest.fixture
def install_cffi(monkeypatch: pytest.MonkeyPatch):
    """Install a routing fake curl_cffi session for the current test."""

    def _install(routes: dict[str, dict[str, Any]]) -> _RoutingCFFISession:
        fake = _RoutingCFFISession(routes)

        async def _ensure(self: EurobetClient) -> _RoutingCFFISession:
            return fake

        monkeypatch.setattr(EurobetClient, "_ensure_cffi_session", _ensure)
        return fake

    return _install


@respx.mock
async def test_scrape_end_to_end_ingests_rows(
    lake: Lake,
    top_disciplines_payload: dict[str, Any],
    meeting_payload: dict[str, Any],
    event_payload: dict[str, Any],
    install_cffi,
) -> None:
    respx.get(
        f"{EUROBET_BASE}/prematch-homepage-service/api/v2/sport-schedule"
        f"/services/top-disciplines/1/calcio"
    ).mock(return_value=httpx.Response(200, json=top_disciplines_payload))

    install_cffi({"detail-service": meeting_payload, "/event/": event_payload})
    # "/event/" comes second but _RoutingCFFISession iterates in insertion order,
    # so we must put the event route first to win over "detail-service":
    # rebuild with explicit ordering.
    install_cffi(
        {
            "/services/event/": event_payload,
            "/services/meeting/": meeting_payload,
        }
    )

    result = await scrape(
        lake,
        leagues=[League.SERIE_A],
        event_concurrency=2,
    )
    assert result.status == "success"
    assert result.per_league_events["serie_a"] >= 1
    assert result.rows_written > 0
    assert result.per_market_rows["match_1x2"] > 0
    assert result.per_market_rows["goals_over_under"] > 0
    assert result.ingest_report is not None


@respx.mock
async def test_scrape_is_idempotent_on_rerun(
    lake: Lake,
    top_disciplines_payload: dict[str, Any],
    meeting_payload: dict[str, Any],
    event_payload: dict[str, Any],
    install_cffi,
) -> None:
    respx.get(
        f"{EUROBET_BASE}/prematch-homepage-service/api/v2/sport-schedule"
        f"/services/top-disciplines/1/calcio"
    ).mock(return_value=httpx.Response(200, json=top_disciplines_payload))
    install_cffi(
        {
            "/services/event/": event_payload,
            "/services/meeting/": meeting_payload,
        }
    )

    captured = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
    result1 = await scrape(
        lake,
        leagues=[League.SERIE_A],
        event_concurrency=1,
        run_id="r1",
        captured_at=captured,
    )
    install_cffi(
        {
            "/services/event/": event_payload,
            "/services/meeting/": meeting_payload,
        }
    )
    result2 = await scrape(
        lake,
        leagues=[League.SERIE_A],
        event_concurrency=1,
        run_id="r2",
        captured_at=captured,
    )
    assert result1.rows_written > 0
    # Every row in the second pass is skipped as a duplicate; nothing new lands.
    assert result2.ingest_report is not None
    assert result2.ingest_report.rows_received == result1.ingest_report.rows_received  # type: ignore[union-attr]
    assert result2.rows_written == 0
    assert (
        result2.ingest_report.rows_skipped_duplicate
        == result2.ingest_report.rows_received
    )


@respx.mock
async def test_scrape_logs_scrape_run(
    lake: Lake,
    top_disciplines_payload: dict[str, Any],
    meeting_payload: dict[str, Any],
    event_payload: dict[str, Any],
    install_cffi,
) -> None:
    respx.get(
        f"{EUROBET_BASE}/prematch-homepage-service/api/v2/sport-schedule"
        f"/services/top-disciplines/1/calcio"
    ).mock(return_value=httpx.Response(200, json=top_disciplines_payload))
    install_cffi(
        {
            "/services/event/": event_payload,
            "/services/meeting/": meeting_payload,
        }
    )
    result = await scrape(lake, leagues=[League.SERIE_A], run_id="abc123")
    # scrape_runs land as a partitioned parquet file under the lake layout.
    runs_root = lake.layout.scrape_runs_root
    parquet_files = list(runs_root.rglob("*.parquet"))
    assert parquet_files, "no scrape_runs partition was materialized"
    import polars as pl  # noqa: PLC0415 - local import keeps tests cheap

    frame = pl.concat(
        [pl.read_parquet(p) for p in parquet_files], how="diagonal_relaxed"
    )
    assert "abc123" in frame["run_id"].to_list()
    assert Bookmaker.EUROBET.value in frame["bookmaker"].to_list()
    assert result.status in {"success", "partial"}


@respx.mock
async def test_scrape_survives_top_disciplines_failure(
    lake: Lake,
    meeting_payload: dict[str, Any],
    event_payload: dict[str, Any],
    install_cffi,
) -> None:
    respx.get(
        f"{EUROBET_BASE}/prematch-homepage-service/api/v2/sport-schedule"
        f"/services/top-disciplines/1/calcio"
    ).mock(return_value=httpx.Response(500, text="oops"))
    install_cffi(
        {
            "/services/event/": event_payload,
            "/services/meeting/": meeting_payload,
        }
    )
    result = await scrape(
        lake, leagues=[League.SERIE_A], event_concurrency=1, run_id="r3"
    )
    # Even with the homepage feed dead, the meeting feed still produces rows.
    assert result.rows_written > 0
    assert result.status == "partial"
    assert any("top_disciplines" in err for err in result.errors)
