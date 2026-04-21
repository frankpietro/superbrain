"""Unit tests for the football-data.co.uk source fetcher."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from superbrain.core.models import League
from superbrain.scrapers.historical.sources import football_data

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "historical" / "football_data"
SERIE_A_CSV = FIXTURES / "serie_a_2023-24.csv"


def test_season_tag_round_trip() -> None:
    assert football_data.season_tag("2023-24") == "2324"
    assert football_data.season_tag("2020-21") == "2021"


def test_season_tag_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        football_data.season_tag("2023/24")


def test_parse_csv_shapes_and_columns() -> None:
    df = football_data.parse_csv(SERIE_A_CSV.read_bytes(), league=League.SERIE_A, season="2023-24")
    assert df.height == 5
    assert {
        "home_team_raw",
        "away_team_raw",
        "home_goals",
        "away_goals",
        "source",
        "league",
        "season",
        "match_date",
    }.issubset(df.columns)
    assert set(df["source"].to_list()) == {"football_data"}
    assert set(df["league"].to_list()) == {"serie_a"}
    assert df["match_date"][0].year == 2023


def test_parse_csv_empty_bytes_returns_empty_frame() -> None:
    df = football_data.parse_csv(b"", league=League.SERIE_A, season="2023-24")
    assert df.height == 0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_league_season_404_returns_empty() -> None:
    url = football_data.build_url(League.SERIE_A, "2023-24")
    respx.get(url).mock(return_value=httpx.Response(404))
    df = await football_data.fetch_league_season(League.SERIE_A, "2023-24")
    assert df.height == 0
    assert "source" in df.columns


@pytest.mark.asyncio
@respx.mock
async def test_fetch_league_season_happy_path() -> None:
    url = football_data.build_url(League.SERIE_A, "2023-24")
    respx.get(url).mock(return_value=httpx.Response(200, content=SERIE_A_CSV.read_bytes()))
    df = await football_data.fetch_league_season(League.SERIE_A, "2023-24")
    assert df.height == 5
    assert df["home_team_raw"][0] == "Frosinone"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_league_season_empty_body_returns_empty() -> None:
    url = football_data.build_url(League.SERIE_A, "2023-24")
    respx.get(url).mock(return_value=httpx.Response(200, content=b""))
    df = await football_data.fetch_league_season(League.SERIE_A, "2023-24")
    assert df.height == 0
