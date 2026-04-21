"""Smoke tests for :mod:`superbrain.scheduler.jobs`.

The jobs never touch live HTTP — we inject stub coroutines that stand in
for the real scrapers. The goal is to verify:

* The scheduler-level ``ScrapeRun`` row is always written.
* Success, partial, failure, and timeout paths all produce a sensible
  audit row.
* Scraper return values (dataclass vs. :class:`IngestReport`) are
  normalised.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import polars as pl

from superbrain.core.models import Bookmaker, IngestProvenance, IngestReport, OddsSnapshot
from superbrain.data.connection import Lake
from superbrain.scheduler.jobs import (
    JobName,
    backfill_historical,
    scrape_eurobet,
    scrape_goldbet,
    scrape_sisal,
)


@dataclass
class _StubSisalResult:
    rows_written: int
    rows_received: int
    rows_rejected: int
    status: str = "success"
    errors: list[str] = field(default_factory=list)


async def _ok_sisal_stub(lake: Lake, **kwargs: object) -> _StubSisalResult:
    # Monkey-patched-scraper path: return three synthetic snapshots worth
    # of work and leave the actual ingestion to a separate test. The
    # smoke is about the audit row, not the Sisal HTTP client.
    return _StubSisalResult(rows_written=3, rows_received=3, rows_rejected=0)


async def _goldbet_stub(lake: Lake, **kwargs: object) -> IngestReport:
    return IngestReport(rows_received=5, rows_written=5)


async def _eurobet_partial_stub(lake: Lake, **kwargs: object) -> _StubSisalResult:
    return _StubSisalResult(
        rows_written=10,
        rows_received=12,
        rows_rejected=2,
        status="partial",
        errors=["event:abc:oops"],
    )


async def _boom_stub(lake: Lake, **kwargs: object) -> _StubSisalResult:
    raise RuntimeError("stub crash")


async def _slow_stub(lake: Lake, **kwargs: object) -> _StubSisalResult:
    await asyncio.sleep(2.0)
    return _StubSisalResult(rows_written=0, rows_received=0, rows_rejected=0)


async def test_scrape_sisal_logs_scraperun(
    lake: Lake, synthetic_snapshots: list[OddsSnapshot]
) -> None:
    # The brief asks for a smoke test that records a ``ScrapeRun`` row via
    # a monkey-patched scraper that returns three synthetic snapshots.
    # We bolt that onto the real job by ingesting the snapshots inside
    # the stub so the scheduler's own audit row captures rows_written=3.
    async def stub(lake_inner: Lake, **kwargs: object) -> _StubSisalResult:
        provenance = IngestProvenance(
            source="test.sisal",
            run_id="unit-run",
            actor="unit-test",
            captured_at=synthetic_snapshots[0].captured_at,
            bookmaker=Bookmaker.SISAL,
        )
        report = lake_inner.ingest_odds(synthetic_snapshots, provenance=provenance)
        return _StubSisalResult(
            rows_written=report.rows_written,
            rows_received=report.rows_received,
            rows_rejected=0,
        )

    run = await scrape_sisal(lake, scrape_fn=stub)
    assert run.status == "success"
    assert run.bookmaker is Bookmaker.SISAL
    assert run.scraper == f"scheduler.{JobName.SISAL.value}"
    assert run.rows_written == 3
    assert run.finished_at is not None
    assert run.finished_at >= run.started_at

    # The audit row must be on disk.
    audit_files = list((lake.root / "scrape_runs").rglob("*.parquet"))
    assert audit_files, "expected scrape_runs partition to contain rows"
    df = pl.read_parquet(audit_files)
    assert (df["run_id"] == run.run_id).any()


async def test_scrape_goldbet_handles_ingest_report(lake: Lake) -> None:
    run = await scrape_goldbet(lake, scrape_fn=_goldbet_stub)
    assert run.status == "success"
    assert run.bookmaker is Bookmaker.GOLDBET


async def test_scrape_eurobet_propagates_partial(lake: Lake) -> None:
    run = await scrape_eurobet(lake, scrape_fn=_eurobet_partial_stub)
    assert run.status == "partial"
    assert run.rows_written == 10
    assert run.rows_rejected == 2
    assert run.error_message is not None and "event:abc" in run.error_message


async def test_scrape_sisal_captures_exception(lake: Lake) -> None:
    run = await scrape_sisal(lake, scrape_fn=_boom_stub)
    assert run.status == "failed"
    assert run.rows_written == 0
    assert run.error_message is not None and "stub crash" in run.error_message


async def test_scrape_sisal_timeout(lake: Lake) -> None:
    run = await scrape_sisal(lake, scrape_fn=_slow_stub, timeout_seconds=1)
    assert run.status == "failed"
    assert run.error_message is not None and "timeout" in run.error_message


async def test_backfill_historical_uses_stub(lake: Lake) -> None:
    @dataclass
    class _PerLS:
        league: str = "serie_a"
        season: str = "2024-25"
        rejected: int = 0
        errors: list[str] = field(default_factory=list)

    @dataclass
    class _StubReport:
        total_matches_written: int = 42
        total_stats_written: int = 84
        total_elo_written: int = 0
        per_league_season: list[_PerLS] = field(default_factory=lambda: [_PerLS()])

    async def stub(
        lake_inner: Lake, *, leagues: object, seasons: object, sources: object
    ) -> _StubReport:
        return _StubReport()

    run = await backfill_historical(
        lake,
        leagues=("serie_a",),
        seasons=("2024-25",),
        sources=("football_data",),
        backfill_fn=stub,
    )
    assert run.status == "success"
    assert run.bookmaker is None
    assert run.scraper == f"scheduler.{JobName.HISTORICAL.value}"
    assert run.rows_written == 42 + 84
