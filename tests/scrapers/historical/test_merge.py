"""Tests for the cross-source merge."""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl

from superbrain.core.models import League, compute_match_id
from superbrain.scrapers.historical.merge import merge_sources


def _fd_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "home_team_raw": ["Roma", "Frosinone", "Milan"],
            "away_team_raw": ["Lazio", "Napoli", "Inter"],
            "match_date": [date(2024, 3, 1), date(2024, 3, 2), date(2024, 3, 3)],
            "home_goals": [2, 1, 0],
            "away_goals": [1, 3, 0],
            "ht_home_goals": [1, 1, 0],
            "ht_away_goals": [0, 2, 0],
            "home_shots": [12, 8, 15],
            "away_shots": [10, 14, 16],
            "home_shots_on_target": [5, 3, 4],
            "away_shots_on_target": [4, 6, 5],
            "home_corners": [5, 3, 7],
            "away_corners": [4, 7, 8],
            "home_fouls": [11, 14, 10],
            "away_fouls": [12, 12, 11],
            "home_yellow_cards": [2, 2, 3],
            "away_yellow_cards": [3, 1, 2],
            "home_red_cards": [0, 0, 0],
            "away_red_cards": [0, 0, 1],
            "source": ["football_data"] * 3,
            "league": ["serie_a"] * 3,
            "season": ["2023-24"] * 3,
        }
    )


def _us_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "understat_match_id": ["1", "2", "3"],
            "is_result": [True, True, True],
            "home_team_raw": ["Roma", "Frosinone", "AC Milan"],
            "away_team_raw": ["Lazio", "Napoli", "Inter"],
            "home_goals": [2, 1, 0],
            "away_goals": [1, 3, 0],
            "home_xg": [1.9, 1.2, 0.7],
            "away_xg": [1.0, 2.4, 1.1],
            "forecast_home": [0.5, 0.3, 0.35],
            "forecast_draw": [0.25, 0.25, 0.30],
            "forecast_away": [0.25, 0.45, 0.35],
            "datetime": [None, None, None],
            "match_date": [date(2024, 3, 1), date(2024, 3, 2), date(2024, 3, 3)],
            "source": ["understat"] * 3,
            "league": ["serie_a"] * 3,
            "season": ["2023-24"] * 3,
        }
    )


def test_merge_produces_matches_and_stats() -> None:
    merged = merge_sources(
        league=League.SERIE_A,
        season="2023-24",
        football_data=_fd_frame(),
        understat=_us_frame(),
        ingested_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    assert len(merged.matches) == 3
    assert len(merged.team_match_stats) == 6
    assert merged.rejected == 0

    ids = {m.match_id for m in merged.matches}
    assert compute_match_id("Roma", "Lazio", date(2024, 3, 1), League.SERIE_A) in ids
    assert compute_match_id("Milan", "Inter", date(2024, 3, 3), League.SERIE_A) in ids

    roma_match = next(m for m in merged.matches if m.home_team == "Roma")
    assert roma_match.home_goals == 2
    assert roma_match.away_goals == 1
    assert roma_match.source == "football_data+understat"

    roma_home_stats = next(s for s in merged.team_match_stats if s.team == "Roma" and s.is_home)
    assert roma_home_stats.goals == 2
    assert roma_home_stats.goals_conceded == 1
    assert roma_home_stats.ht_goals == 1
    assert roma_home_stats.ht_goals_conceded == 0
    assert roma_home_stats.shots == 12
    assert roma_home_stats.corners == 5
    assert roma_home_stats.xg is not None and abs(roma_home_stats.xg - 1.9) < 1e-9
    assert roma_home_stats.xga is not None and abs(roma_home_stats.xga - 1.0) < 1e-9


def test_merge_left_outer_when_only_football_data_present() -> None:
    merged = merge_sources(
        league=League.SERIE_A,
        season="2023-24",
        football_data=_fd_frame(),
        understat=None,
        fbref=None,
        ingested_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    assert len(merged.matches) == 3
    milan_stats = next(s for s in merged.team_match_stats if s.team == "Milan" and s.is_home)
    assert milan_stats.xg is None
    assert milan_stats.xga is None
    assert milan_stats.shots == 15


def test_merge_canonicalizes_team_aliases() -> None:
    merged = merge_sources(
        league=League.SERIE_A,
        season="2023-24",
        football_data=None,
        understat=_us_frame(),
        ingested_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    teams = {m.home_team for m in merged.matches}
    assert "Milan" in teams
    assert "AC Milan" not in teams


def test_merge_empty_sources_returns_empty() -> None:
    merged = merge_sources(
        league=League.SERIE_A,
        season="2023-24",
        ingested_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    assert merged.matches == []
    assert merged.team_match_stats == []
