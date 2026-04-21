"""Public health endpoint.

Unauthenticated by design: platform smoke-checks (Fly.io, Vercel, uptime
monitors) have to hit this without carrying a bearer token.
"""

from __future__ import annotations

import os
from typing import Annotated

import anyio
import polars as pl
from fastapi import APIRouter, Depends

from superbrain.api.deps import get_lake
from superbrain.api.schemas import HealthResponse, HealthScrapeRun
from superbrain.data.connection import Lake
from superbrain.data.schemas import SCRAPE_RUNS_SCHEMA

router = APIRouter(tags=["health"])

_BOOKMAKERS = ("sisal", "goldbet", "eurobet")
_HISTORICAL_SCRAPER_KEY = "historical"


@router.get("/health", response_model=HealthResponse)
async def health(lake: Annotated[Lake, Depends(get_lake)]) -> HealthResponse:
    """Return process liveness, lake presence, and latest scrape timestamps."""
    runs = await anyio.to_thread.run_sync(_load_latest_runs, lake)
    return HealthResponse(
        status="ok",
        git_sha=os.environ.get("SUPERBRAIN_GIT_SHA"),
        lake_present=lake.root.exists(),
        last_scrape_runs=runs,
    )


def _load_latest_runs(lake: Lake) -> dict[str, HealthScrapeRun | None]:
    """Load the most recent ``scrape_runs`` row per bookmaker + historical."""
    out: dict[str, HealthScrapeRun | None] = {}
    for slug in _BOOKMAKERS:
        out[slug] = _latest_for(lake, bookmaker=slug)
    out[_HISTORICAL_SCRAPER_KEY] = _latest_for(lake, bookmaker=None, scraper_contains="historical")
    return out


def _latest_for(
    lake: Lake, *, bookmaker: str | None, scraper_contains: str | None = None
) -> HealthScrapeRun | None:
    frame = _read_scrape_runs(lake, bookmaker=bookmaker)
    if frame is None or frame.is_empty():
        return None
    if scraper_contains is not None:
        frame = frame.filter(pl.col("scraper").str.contains(scraper_contains))
        if frame.is_empty():
            return None
    frame = frame.sort("started_at", descending=True).head(1)
    row = frame.row(0, named=True)
    return HealthScrapeRun(
        bookmaker=row.get("bookmaker") or (bookmaker or "unknown"),
        last_started_at=row.get("started_at"),
        last_finished_at=row.get("finished_at"),
        last_status=row.get("status"),
    )


def _read_scrape_runs(lake: Lake, *, bookmaker: str | None) -> pl.DataFrame | None:
    root = lake.layout.scrape_runs_root
    if not root.exists():
        return None
    if bookmaker is not None:
        paths = list(root.glob(f"bookmaker={bookmaker}/year_month=*/*.parquet"))
    else:
        paths = list(root.glob("bookmaker=*/year_month=*/*.parquet"))
    if not paths:
        return pl.DataFrame(schema=SCRAPE_RUNS_SCHEMA)
    return pl.read_parquet(paths)
