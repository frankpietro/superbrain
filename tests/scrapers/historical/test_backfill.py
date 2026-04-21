"""End-to-end test for ``scripts/backfill_historical.py`` (mocked HTTP)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import respx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import backfill_historical as bf  # noqa: E402

from superbrain.core.models import League  # noqa: E402
from superbrain.data.connection import Lake  # noqa: E402
from superbrain.scrapers.historical.sources import football_data, understat  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "historical"
FD_CSV = FIXTURES / "football_data" / "serie_a_2023-24.csv"
US_JSON = FIXTURES / "understat" / "serie_a_2023-24.json"


@pytest.mark.asyncio
@respx.mock
async def test_backfill_end_to_end_and_idempotent(tmp_path: Path) -> None:
    fd_url = football_data.build_url(League.SERIE_A, "2023-24")
    us_url = understat.build_url(League.SERIE_A, "2023-24")
    respx.get(fd_url).mock(return_value=httpx.Response(200, content=FD_CSV.read_bytes()))
    respx.get(us_url).mock(return_value=httpx.Response(200, text=US_JSON.read_text()))

    lake = Lake(tmp_path / "lake")
    lake.ensure_schema()

    report = await bf.run_backfill(
        lake,
        leagues=[League.SERIE_A],
        seasons=["2023-24"],
        sources=["football_data", "understat"],
    )
    assert report.total_matches_written == 5
    assert report.total_stats_written == 10
    per = report.per_league_season[0]
    assert per.matches_received == 5
    assert per.stats_received == 10
    assert per.errors == []

    matches = lake.read_matches(league="serie_a", season="2023-24")
    assert matches.height == 5

    respx.get(fd_url).mock(return_value=httpx.Response(200, content=FD_CSV.read_bytes()))
    respx.get(us_url).mock(return_value=httpx.Response(200, text=US_JSON.read_text()))
    second = await bf.run_backfill(
        lake,
        leagues=[League.SERIE_A],
        seasons=["2023-24"],
        sources=["football_data", "understat"],
    )
    assert second.total_matches_written == 0
    assert second.total_stats_written == 0
    assert second.per_league_season[0].matches_skipped == 5
    assert second.per_league_season[0].stats_skipped == 10


@pytest.mark.asyncio
@respx.mock
async def test_backfill_survives_understat_down(tmp_path: Path) -> None:
    fd_url = football_data.build_url(League.SERIE_A, "2023-24")
    us_url = understat.build_url(League.SERIE_A, "2023-24")
    respx.get(fd_url).mock(return_value=httpx.Response(200, content=FD_CSV.read_bytes()))
    respx.get(us_url).mock(return_value=httpx.Response(503))

    lake = Lake(tmp_path / "lake")
    lake.ensure_schema()

    report = await bf.run_backfill(
        lake,
        leagues=[League.SERIE_A],
        seasons=["2023-24"],
        sources=["football_data", "understat"],
    )
    per = report.per_league_season[0]
    assert per.errors, "understat 503 must be captured as an error, not silently swallowed"
    assert per.matches_written == 0


def test_season_end_date_computation() -> None:
    from datetime import date as _date  # noqa: PLC0415

    assert bf._season_end_date("2023-24") == _date(2024, 6, 1)
    assert bf._season_end_date("2020-21") == _date(2021, 6, 1)


def test_parse_sources_rejects_unknown() -> None:
    with pytest.raises(SystemExit):
        bf._parse_sources("football_data,not_a_source")
