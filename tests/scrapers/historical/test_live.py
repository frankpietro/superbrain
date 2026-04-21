"""Live-smoke test for the historical backfill.

Skipped by default. Enable with ``SUPERBRAIN_LIVE_TESTS=1`` to hit the real
football-data.co.uk / Understat endpoints. Asserts >20 rows land when we
fetch Serie A 2023-24; does **not** enable FBref or ClubElo (too slow).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from superbrain.core.models import League
from superbrain.data.connection import Lake
from superbrain.scrapers.historical.sources import football_data, understat

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

LIVE_ENV = "SUPERBRAIN_LIVE_TESTS"

pytestmark = pytest.mark.skipif(
    os.getenv(LIVE_ENV, "0") != "1",
    reason=f"live test; set {LIVE_ENV}=1 to run",
)


@pytest.mark.asyncio
async def test_football_data_live_serie_a_2023_24() -> None:
    df = await football_data.fetch_league_season(League.SERIE_A, "2023-24")
    assert df.height > 20, f"expected >20 rows, got {df.height}"
    assert {"home_team_raw", "away_team_raw", "home_goals"}.issubset(df.columns)


@pytest.mark.asyncio
async def test_understat_live_serie_a_2023_24() -> None:
    df = await understat.fetch_league_season(League.SERIE_A, "2023-24")
    assert df.height > 20, f"expected >20 rows, got {df.height}"
    assert df["home_xg"].drop_nulls().len() > 20


@pytest.mark.asyncio
async def test_end_to_end_live_backfill_lands_rows(tmp_path: Path) -> None:
    import backfill_historical as bf  # noqa: PLC0415

    lake = Lake(tmp_path / "lake")
    lake.ensure_schema()
    report = await bf.run_backfill(
        lake,
        leagues=[League.SERIE_A],
        seasons=["2023-24"],
        sources=["football_data", "understat"],
    )
    assert report.total_matches_written > 20
    assert report.total_stats_written > 40
