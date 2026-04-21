"""Scrapers router: recent runs and an aggregated health view."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import anyio
import polars as pl
from fastapi import APIRouter, Depends, Query

from superbrain.api.deps import get_lake
from superbrain.api.schemas import (
    Page,
    ScraperHistoryEntry,
    ScrapersStatus,
    ScrapersStatusBookmaker,
    ScrapeRunRow,
)
from superbrain.data.connection import Lake
from superbrain.data.schemas import SCRAPE_RUNS_SCHEMA

router = APIRouter(prefix="/scrapers", tags=["scrapers"])

_MAX_LIMIT = 500
_KNOWN_BOOKMAKERS = ("sisal", "goldbet", "eurobet")
# Scrapers historically wrote "success" for happy-path runs; the API normalises
# everything to "ok" at the boundary so the SPA has a single canonical value.
_HEALTHY_STATUSES = frozenset({"ok", "success"})
_HISTORY_LIMIT = 10


@router.get("/runs", response_model=Page[ScrapeRunRow])
async def list_runs(
    lake: Annotated[Lake, Depends(get_lake)],
    bookmaker: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 50,
) -> Page[ScrapeRunRow]:
    """Return the most recent ``ScrapeRun`` rows, newest first."""
    rows = await anyio.to_thread.run_sync(_list_runs_sync, lake, bookmaker, limit)
    return Page[ScrapeRunRow](items=rows, count=len(rows), next_cursor=None)


@router.get("/status", response_model=ScrapersStatus)
async def status(lake: Annotated[Lake, Depends(get_lake)]) -> ScrapersStatus:
    """Aggregate latest-run + last-24h counters + short history per bookmaker."""
    blocks = await anyio.to_thread.run_sync(_status_sync, lake)
    return ScrapersStatus(items=blocks)


def _list_runs_sync(lake: Lake, bookmaker: str | None, limit: int) -> list[ScrapeRunRow]:
    frame = _read_runs_frame(lake, bookmaker=bookmaker)
    if frame.is_empty():
        return []
    frame = frame.sort("started_at", descending=True).head(limit)
    return [_row_to_model(r) for r in frame.iter_rows(named=True)]


def _status_sync(lake: Lake) -> list[ScrapersStatusBookmaker]:
    all_frame = _read_runs_frame(lake, bookmaker=None)
    cutoff = datetime.now(tz=UTC) - timedelta(hours=24)
    healthy_list = list(_HEALTHY_STATUSES)
    blocks: list[ScrapersStatusBookmaker] = []
    for slug in _KNOWN_BOOKMAKERS:
        sub = (
            all_frame.filter(pl.col("bookmaker") == slug) if not all_frame.is_empty() else all_frame
        )
        last_row: ScrapeRunRow | None = None
        runs_24h = 0
        rows_written_24h = 0
        errors_24h = 0
        history: list[ScraperHistoryEntry] = []
        healthy = False
        if not sub.is_empty():
            sorted_sub = sub.sort("started_at", descending=True)
            last = sorted_sub.head(1).row(0, named=True)
            last_row = _row_to_model(last)
            recent = sub.filter(pl.col("started_at") >= cutoff)
            runs_24h = recent.height
            if recent.height:
                rows_written_24h = int(recent.get_column("rows_written").fill_null(0).sum() or 0)
                errors_24h = int(recent.filter(~pl.col("status").is_in(healthy_list)).height)
            healthy = last_row.status == "ok" and errors_24h == 0
            history = [
                ScraperHistoryEntry(
                    run_id=str(row["run_id"]),
                    started_at=row["started_at"],
                    rows_written=int(row.get("rows_written") or 0),
                    status=_normalise_status(row.get("status")),
                )
                for row in sorted_sub.head(_HISTORY_LIMIT).iter_rows(named=True)
            ]
        blocks.append(
            ScrapersStatusBookmaker(
                bookmaker=slug,
                last_run=last_row,
                healthy=healthy,
                runs_24h=runs_24h,
                rows_written_24h=rows_written_24h,
                errors_24h=errors_24h,
                unmapped_markets_top=[],
                history=history,
            )
        )
    return blocks


def _normalise_status(raw: object) -> str:
    """Canonicalise the persisted run status for the API boundary.

    Scrapers historically wrote ``"success"`` for happy-path runs; this maps
    them to ``"ok"`` so the SPA only has to branch on one value. Anything else
    (``partial``, ``failed``, ``timeout``, …) is passed through as-is.
    """
    if raw is None:
        return "unknown"
    value = str(raw)
    return "ok" if value in _HEALTHY_STATUSES else value


def _read_runs_frame(lake: Lake, *, bookmaker: str | None) -> pl.DataFrame:
    root = lake.layout.scrape_runs_root
    if not root.exists():
        return pl.DataFrame(schema=SCRAPE_RUNS_SCHEMA)
    if bookmaker is not None:
        paths = list(root.glob(f"bookmaker={bookmaker}/year_month=*/*.parquet"))
    else:
        paths = list(root.glob("bookmaker=*/year_month=*/*.parquet"))
    if not paths:
        return pl.DataFrame(schema=SCRAPE_RUNS_SCHEMA)
    return pl.read_parquet(paths)


def _row_to_model(row: dict[str, Any]) -> ScrapeRunRow:
    rows_written = row.get("rows_written") or 0
    rows_rejected = row.get("rows_rejected") or 0
    return ScrapeRunRow(
        run_id=str(row["run_id"]),
        bookmaker=(str(row["bookmaker"]) if row.get("bookmaker") else None),
        scraper=str(row["scraper"]),
        started_at=row["started_at"],
        finished_at=row.get("finished_at"),
        status=_normalise_status(row.get("status")),
        rows_written=int(rows_written),
        rows_rejected=int(rows_rejected),
        error_message=(str(row["error_message"]) if row.get("error_message") else None),
        host=(str(row["host"]) if row.get("host") else None),
    )
