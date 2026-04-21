"""Live-smoke test for the Sisal scraper.

Gated behind ``SUPERBRAIN_LIVE_TESTS=1``. Talks to the real
``betting.sisal.it`` API, fetches the Serie A tree + one event, and
asserts that at least one ``OddsSnapshot`` validates end-to-end. This is
the check the operator runs before flipping the scheduler on.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from superbrain.core.models import League
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.sisal.scraper import reset_tree_cache, scrape

LIVE_ENABLED = os.environ.get("SUPERBRAIN_LIVE_TESTS") == "1"


pytestmark = [
    pytest.mark.skipif(not LIVE_ENABLED, reason="set SUPERBRAIN_LIVE_TESTS=1 to enable"),
    pytest.mark.integration,
    pytest.mark.slow,
]


@pytest.mark.asyncio
async def test_live_serie_a_scrape(tmp_path: Path) -> None:
    reset_tree_cache()
    lake = Lake(root=tmp_path / "lake")
    lake.ensure_schema()
    result = await scrape(lake, leagues=[League.SERIE_A], event_concurrency=2)
    # The season is live in April 2026; Sisal always lists at least one
    # Serie A fixture in the prematch window.
    assert result.per_league_events.get("serie_a", 0) > 0
    assert result.rows_written > 0, f"errors: {result.errors}"
    assert result.status in {"success", "partial"}
    # Sanity: some of the minimum covered markets must have landed.
    must_have = {"match_1x2", "goals_over_under", "goals_both_teams"}
    missing = must_have - set(result.per_market_rows)
    assert not missing, f"missing expected market families: {missing}"
