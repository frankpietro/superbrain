"""Unit tests for the Understat source fetcher."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from superbrain.core.models import League
from superbrain.scrapers.historical.sources import understat

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "historical" / "understat"
SERIE_A_JSON = FIXTURES / "serie_a_2023-24.json"


def test_season_start_year() -> None:
    assert understat.season_start_year("2023-24") == "2023"
    assert understat.season_start_year("2020-21") == "2020"


def test_parse_payload_populates_rows() -> None:
    df = understat.parse_payload(SERIE_A_JSON.read_text(), league=League.SERIE_A, season="2023-24")
    assert df.height == 5
    assert df["home_team_raw"][0] == "Frosinone"
    assert df["away_team_raw"][0] == "Napoli"
    assert abs(df["home_xg"][0] - 1.4) < 1e-9
    assert df["match_date"][0].year == 2023


def test_parse_payload_empty_returns_empty() -> None:
    df = understat.parse_payload("{}", league=League.SERIE_A, season="2023-24")
    assert df.height == 0
    assert "home_team_raw" in df.columns


def test_parse_payload_malformed_returns_empty() -> None:
    df = understat.parse_payload("not json", league=League.SERIE_A, season="2023-24")
    assert df.height == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_league_season_happy_path() -> None:
    url = understat.build_url(League.SERIE_A, "2023-24")
    respx.get(url).mock(return_value=httpx.Response(200, text=SERIE_A_JSON.read_text()))
    df = await understat.fetch_league_season(League.SERIE_A, "2023-24")
    assert df.height == 5
    assert df["home_team_raw"][4] == "Hellas Verona"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_league_season_404_returns_empty() -> None:
    url = understat.build_url(League.SERIE_A, "2023-24")
    respx.get(url).mock(return_value=httpx.Response(404))
    df = await understat.fetch_league_season(League.SERIE_A, "2023-24")
    assert df.height == 0
