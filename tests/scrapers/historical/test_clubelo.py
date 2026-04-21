"""Unit tests for the ClubElo source wrapper (via fake adapter)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from superbrain.core.models import League
from superbrain.scrapers.historical.sources import clubelo


class _FakeClubEloAdapter:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame
        self.calls: list[str | date] = []

    def read_by_date(self, date: str | date) -> pd.DataFrame:
        self.calls.append(date)
        return self._frame


def _snapshot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rank": [1, 2, 3, 4, 5],
            "club": ["Inter", "Juventus", "Milan", "Arsenal", "Real Madrid"],
            "country": ["ITA", "ITA", "ITA", "ENG", "ESP"],
            "elo": [1950.0, 1910.0, 1905.0, 1990.0, 2015.0],
        }
    )


def test_fetch_snapshot_filters_by_league_countries() -> None:
    adapter = _FakeClubEloAdapter(_snapshot_frame())
    df = clubelo.fetch_snapshot(
        date(2024, 5, 27),
        leagues=[League.SERIE_A],
        adapter=adapter,
    )
    assert df.height == 3
    assert set(df["country"].to_list()) == {"ITA"}
    assert set(df["club"].to_list()) == {"Inter", "Juventus", "Milan"}
    assert df["snapshot_date"][0] == date(2024, 5, 27)


def test_fetch_snapshot_all_leagues_default() -> None:
    adapter = _FakeClubEloAdapter(_snapshot_frame())
    df = clubelo.fetch_snapshot(date(2024, 5, 27), adapter=adapter)
    assert df.height == 5
    assert set(df["country"].to_list()) == {"ITA", "ENG", "ESP"}


def test_fetch_snapshot_empty_source_returns_empty_frame() -> None:
    adapter = _FakeClubEloAdapter(pd.DataFrame())
    df = clubelo.fetch_snapshot(date(2024, 5, 27), adapter=adapter)
    assert df.height == 0
