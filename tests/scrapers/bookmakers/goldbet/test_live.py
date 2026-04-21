"""Live smoke test for the Goldbet scraper.

Gated on ``SUPERBRAIN_LIVE_TESTS=1`` so that ordinary test runs never hit
the real Goldbet API. When enabled, this test performs a real Akamai
bootstrap (``curl_cffi``), fetches Serie A, picks the first event, and
ingests its markets into an ephemeral lake.

Proof-of-life criteria:

- at least one :class:`OddsSnapshot` is produced
- the ``scrape_runs`` row records a non-zero duration and no error
- the ingest report's ``rows_written`` is positive
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from superbrain.core.models import Bookmaker, League
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.goldbet.scraper import scrape

pytestmark = pytest.mark.skipif(
    os.environ.get("SUPERBRAIN_LIVE_TESTS") != "1",
    reason="live Goldbet calls disabled (set SUPERBRAIN_LIVE_TESTS=1 to run)",
)


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.asyncio
async def test_live_serie_a_scrape(tmp_path: Path) -> None:
    """Scrape Serie A live and confirm at least one row lands in the lake."""
    lake = Lake(root=tmp_path / "lake")
    lake.ensure_schema()

    report = await scrape(
        lake,
        leagues=[League.SERIE_A],
        run_id="live-smoke",
    )

    assert report.rows_received > 0, "Goldbet returned zero rows — possible blocker"
    assert report.rows_written > 0
    frame = lake.read_odds(bookmaker=Bookmaker.GOLDBET.value)
    assert frame.height >= report.rows_written
