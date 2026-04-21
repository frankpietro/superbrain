"""Live-smoke test for the Eurobet scraper.

Gated behind ``SUPERBRAIN_LIVE_TESTS=1``. Talks to the real
``www.eurobet.it`` stack -- both the public Next.js / homepage endpoints
(via plain ``httpx``) and the Cloudflare-gated per-event ``detail-service``
(via ``curl_cffi`` with ``impersonate="chrome124"``). This is the check
the operator runs before flipping the phase-10 scheduler on.

The test is resilient to Eurobet's known flakiness: Cloudflare sometimes
refuses the per-event request, and individual meetings occasionally
return a validation error that the scraper already logs and ignores. We
only assert that at least one Serie A event produced at least one
snapshot end-to-end.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from superbrain.core.models import League
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.eurobet.scraper import scrape

LIVE_ENABLED = os.environ.get("SUPERBRAIN_LIVE_TESTS") == "1"


pytestmark = [
    pytest.mark.skipif(
        not LIVE_ENABLED, reason="set SUPERBRAIN_LIVE_TESTS=1 to enable"
    ),
    pytest.mark.integration,
    pytest.mark.slow,
]


@pytest.mark.asyncio
async def test_live_serie_a_scrape(tmp_path: Path) -> None:
    lake = Lake(root=tmp_path / "lake")
    lake.ensure_schema()
    result = await scrape(
        lake, leagues=[League.SERIE_A], event_concurrency=2
    )
    # The season is live in April 2026; Eurobet always lists at least one
    # Serie A fixture in the prematch window.
    assert result.per_league_events.get("serie_a", 0) > 0
    assert result.rows_written > 0, f"errors: {result.errors}"
    assert result.status in {"success", "partial"}
    # Sanity: Eurobet always publishes at minimum the 1X2 family for
    # Serie A top fixtures. O/U and BTTS are optional on individual
    # events -- we don't require them here to keep the smoke stable.
    assert "match_1x2" in result.per_market_rows
