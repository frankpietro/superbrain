"""Unit tests for the FBref source wrapper (via fake adapter)."""

from __future__ import annotations

import pandas as pd
import pytest

from superbrain.core.models import League
from superbrain.scrapers.historical.sources import fbref


class _FakeFBrefAdapter:
    """Fake ``soccerdata.FBref`` surface — no network, no chromedriver."""

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def read_team_match_stats(self, stat_type: str) -> pd.DataFrame:
        return self._frames.get(stat_type, pd.DataFrame())


def _schedule_frame() -> pd.DataFrame:
    """Mimic the index + columns soccerdata returns for ``stat_type='schedule'``."""
    idx = pd.MultiIndex.from_tuples(
        [
            ("ITA-Serie A", "2023-2024", "Frosinone", "2023-08-19 Frosinone-Napoli"),
            ("ITA-Serie A", "2023-2024", "Napoli", "2023-08-19 Frosinone-Napoli"),
            ("ITA-Serie A", "2023-2024", "Genoa", "2023-08-19 Genoa-Fiorentina"),
            ("ITA-Serie A", "2023-2024", "Fiorentina", "2023-08-19 Genoa-Fiorentina"),
        ],
        names=["league", "season", "team", "game"],
    )
    return pd.DataFrame(
        {
            "date": ["2023-08-19"] * 4,
            "venue": ["Home", "Away", "Home", "Away"],
            "opponent": ["Napoli", "Frosinone", "Fiorentina", "Genoa"],
            "poss": [45.0, 55.0, 38.0, 62.0],
        },
        index=idx,
    )


def _misc_frame() -> pd.DataFrame:
    idx = pd.MultiIndex.from_tuples(
        [
            ("ITA-Serie A", "2023-2024", "Frosinone", "2023-08-19 Frosinone-Napoli"),
            ("ITA-Serie A", "2023-2024", "Napoli", "2023-08-19 Frosinone-Napoli"),
            ("ITA-Serie A", "2023-2024", "Genoa", "2023-08-19 Genoa-Fiorentina"),
            ("ITA-Serie A", "2023-2024", "Fiorentina", "2023-08-19 Genoa-Fiorentina"),
        ],
        names=["league", "season", "team", "game"],
    )
    cols = pd.MultiIndex.from_tuples(
        [
            ("Performance", "CrdY"),
            ("Performance", "CrdR"),
            ("Performance", "Fls"),
            ("Performance", "Off"),
            ("Aerial Duels", "Won"),
        ]
    )
    df = pd.DataFrame(
        [[2, 0, 14, 1, 9], [1, 0, 12, 2, 11], [3, 0, 11, 0, 7], [1, 0, 7, 3, 10]],
        index=idx,
        columns=cols,
    )
    return df


def test_fetch_league_season_flattens_and_joins() -> None:
    adapter = _FakeFBrefAdapter({"schedule": _schedule_frame(), "misc": _misc_frame()})
    df = fbref.fetch_league_season(
        League.SERIE_A,
        "2023-24",
        stat_types=("schedule", "misc"),
        adapter=adapter,
    )
    assert df.height == 4
    assert "possession_pct" in df.columns
    assert "yellow_cards" in df.columns
    assert "team_raw" in df.columns
    assert "is_home" in df.columns
    frosinone = df.filter(df["team_raw"] == "Frosinone")
    assert frosinone["is_home"][0] is True
    assert abs(frosinone["possession_pct"][0] - 45.0) < 1e-9
    assert frosinone["yellow_cards"][0] == 2


def test_fetch_league_season_empty_adapter_returns_empty() -> None:
    df = fbref.fetch_league_season(
        League.SERIE_A,
        "2023-24",
        stat_types=("schedule",),
        adapter=_FakeFBrefAdapter({}),
    )
    assert df.height == 0


def test_to_fbref_season_format() -> None:
    assert fbref._to_fbref_season("2023-24") == "2023-2024"
    assert fbref._to_fbref_season("2020-21") == "2020-2021"


def test_to_fbref_season_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        fbref._to_fbref_season("23-24")
