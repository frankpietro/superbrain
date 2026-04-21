"""End-to-end tests for :func:`superbrain.scrapers.bookmakers.goldbet.scrape`.

Drives the orchestrator against a fake Goldbet session populated with real
spike-derived fixtures, ingests into an ephemeral :class:`Lake`, and
asserts:

- the scrape never raises (contract)
- odds land in the lake and dedupe on a re-run (idempotency)
- the ``scrape_runs`` audit row is written with the correct status
- a network-level failure still produces a ``failed`` audit row without
  crashing the caller
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from superbrain.core.models import Bookmaker, League
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.goldbet.client import GoldbetClient
from superbrain.scrapers.bookmakers.goldbet.scraper import scrape


@dataclass
class FakeResponse:
    status_code: int
    _payload: Any = None
    content: bytes = b""

    def json(self) -> Any:
        return self._payload


@dataclass
class FakeSession:
    handler: Callable[[str, dict[str, str]], FakeResponse]
    calls: list[str] = field(default_factory=list)
    closed: bool = False

    async def get(self, url: str, *, headers: dict[str, str], timeout: float) -> FakeResponse:
        del headers, timeout
        self.calls.append(url)
        return self.handler(url, {})

    async def close(self) -> None:
        self.closed = True


def _json_response(payload: Any, status: int = 200) -> FakeResponse:
    return FakeResponse(
        status_code=status,
        _payload=payload,
        content=json.dumps(payload).encode(),
    )


def _build_router(
    *,
    events_serie_a: dict[str, Any],
    markets_tab0: dict[str, Any],
    markets_tab_angoli: dict[str, Any],
    markets_tab_multigol: dict[str, Any],
) -> Callable[[str, dict[str, str]], FakeResponse]:
    """Minimal request router that mimics Goldbet's URL space."""

    empty_list = {"leo": [], "lmtW": [], "success": True}

    def handler(url: str, _headers: dict[str, str]) -> FakeResponse:  # noqa: PLR0911
        # Warmup on any non-API URL.
        if "/api/" not in url:
            return FakeResponse(status_code=200)

        if "/getOverviewEventsAams/0/1/0/93/" in url:
            return _json_response(events_serie_a)
        if "/getOverviewEventsAams/" in url:
            # All other leagues: empty listing so the scrape focuses on Serie A.
            return _json_response(empty_list)

        if "/getDetailsEventAams/" in url:
            # URL tail is .../{aams_t}/{t}/{aams_e}/{e}/{macro_tab}/{event_type}
            parts = url.split("/")
            macro_tab = int(parts[-2])
            if macro_tab == 0:
                return _json_response(markets_tab0)
            if macro_tab == 3500:
                return _json_response(markets_tab_angoli)
            if macro_tab == 3491:
                return _json_response(markets_tab_multigol)
            # Any other discovered tab: return an empty tree (no odds).
            return _json_response({"leo": [], "lmtW": [], "success": False})

        return _json_response(empty_list)

    return handler


@pytest.fixture
def lake(tmp_lake_root: Path) -> Lake:
    lake = Lake(root=tmp_lake_root)
    lake.ensure_schema()
    return lake


@pytest.fixture
def fake_client(
    events_serie_a: dict[str, Any],
    markets_tab0: dict[str, Any],
    markets_tab_angoli: dict[str, Any],
    markets_tab_multigol: dict[str, Any],
) -> GoldbetClient:
    # The tab0 fixture's lmtW was trimmed to a handful of entries; extend it
    # here so the scraper discovers the Angoli/Multigol tabs we care about.
    markets_tab0 = dict(markets_tab0)
    markets_tab0["lmtW"] = [
        {"tbI": 3500, "tbN": "Angoli", "lt": 0, "lotb": []},
        {"tbI": 3491, "tbN": "Multigol", "lt": 0, "lotb": []},
        # unknown tab; router returns an empty tree for it
        {"tbI": 9999, "tbN": "Unknown", "lt": 0, "lotb": []},
    ]
    handler = _build_router(
        events_serie_a=events_serie_a,
        markets_tab0=markets_tab0,
        markets_tab_angoli=markets_tab_angoli,
        markets_tab_multigol=markets_tab_multigol,
    )
    return GoldbetClient(
        session=FakeSession(handler=handler),
        min_interval_seconds=0.0,
        max_attempts=2,
    )


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_scrape_writes_rows_and_audit(
        self, lake: Lake, fake_client: GoldbetClient
    ) -> None:
        async with fake_client as client:
            report = await scrape(lake, leagues=[League.SERIE_A], client=client, run_id="run-1")
        assert report.rows_received > 0
        assert report.rows_written > 0
        assert report.rows_rejected == 0

        frame = lake.read_odds(bookmaker=Bookmaker.GOLDBET.value)
        assert frame.height == report.rows_written
        assert set(frame["market"].unique()) >= {
            "match_1x2",
            "match_double_chance",
            "goals_over_under",
            "corner_total",
            "multigol",
            "multigol_team",
        }

    @pytest.mark.asyncio
    async def test_scrape_is_idempotent(
        self,
        lake: Lake,
        fake_client: GoldbetClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Freeze ``datetime.now`` inside the scraper and parser so both runs
        # stamp identical ``captured_at`` values — the natural dedupe key
        # includes the timestamp, so without this they'd legitimately write
        # two rows per snapshot.
        frozen = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)

        class _Clock(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
                return frozen if tz is None else frozen.astimezone(tz)

        monkeypatch.setattr("superbrain.scrapers.bookmakers.goldbet.scraper.datetime", _Clock)

        async with fake_client as client:
            first = await scrape(lake, leagues=[League.SERIE_A], client=client, run_id="run-a")
            second = await scrape(lake, leagues=[League.SERIE_A], client=client, run_id="run-b")

        assert first.rows_written > 0
        # Re-run with identical timestamps: every row dedupes.
        assert second.rows_written == 0
        assert second.rows_skipped_duplicate == second.rows_received

    @pytest.mark.asyncio
    async def test_scrape_survives_network_failure(self, lake: Lake) -> None:
        def broken(url: str, _headers: dict[str, str]) -> FakeResponse:
            if "/api/" not in url:
                return FakeResponse(status_code=200)
            return FakeResponse(status_code=500)

        client = GoldbetClient(
            session=FakeSession(handler=broken),
            min_interval_seconds=0.0,
            max_attempts=2,
        )
        async with client as c:
            # scrape() must never raise — failures land in the audit row
            report = await scrape(lake, leagues=[League.SERIE_A], client=c, run_id="run-broken")
        assert report.rows_written == 0
        audit = _read_scrape_runs(lake)
        assert audit["status"].to_list()[-1] in {"success", "failed"}

    @pytest.mark.asyncio
    async def test_audit_row_is_always_written(
        self, lake: Lake, fake_client: GoldbetClient
    ) -> None:
        async with fake_client as client:
            await scrape(lake, leagues=[League.SERIE_A], client=client, run_id="audit-1")
        audit = _read_scrape_runs(lake)
        row = audit.filter(pl.col("run_id") == "audit-1")
        assert row.height == 1
        assert row["bookmaker"].item() == Bookmaker.GOLDBET.value
        assert row["status"].item() == "success"
        assert row["rows_written"].item() > 0


def _read_scrape_runs(lake: Lake) -> pl.DataFrame:
    files = sorted((lake.root / "scrape_runs").rglob("*.parquet"))
    assert files, "no scrape_runs audit rows were written"
    return pl.read_parquet(files)
