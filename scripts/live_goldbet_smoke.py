"""Ad-hoc live smoke measurement for the Goldbet scraper.

Scrapes Serie A only (to keep the measurement under a few minutes),
writes into a throwaway lake, and prints a structured summary.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from superbrain.core.models import Bookmaker, League
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.goldbet.scraper import scrape


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        lake_root = Path(tmp) / "lake"
        lake = Lake(root=lake_root)
        lake.ensure_schema()

        t0 = time.monotonic()
        report = await scrape(
            lake,
            leagues=[League.SERIE_A],
            run_id="phase3-live-smoke",
        )
        elapsed = time.monotonic() - t0

        frame = lake.read_odds(bookmaker=Bookmaker.GOLDBET.value)

        print("=== Goldbet live smoke ===")
        print(f"duration_seconds       : {elapsed:.1f}")
        print(f"rows_received          : {report.rows_received}")
        print(f"rows_written           : {report.rows_written}")
        print(f"rows_skipped_duplicate : {report.rows_skipped_duplicate}")
        print(f"rows_rejected          : {report.rows_rejected}")
        print(f"lake_rows_after_read   : {frame.height}")
        if frame.height:
            unique_matches = frame.select("match_id").n_unique()
            unique_markets = frame.select("market").n_unique()
            print(f"unique_matches         : {unique_matches}")
            print(f"unique_markets         : {unique_markets}")


if __name__ == "__main__":
    asyncio.run(main())
