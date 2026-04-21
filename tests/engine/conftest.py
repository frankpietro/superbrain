"""Shared fixtures for engine tests.

Builds a tiny synthetic lake (8 teams, one season of round-robin matches,
deterministic stat distributions) that every integration test can reuse.
"""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from superbrain.core.markets import Market
from superbrain.core.models import (
    Bookmaker,
    IngestProvenance,
    League,
    Match,
    OddsSnapshot,
    TeamMatchStats,
    compute_match_id,
)
from superbrain.data.connection import Lake

SYNTH_SEASON = "2023-24"
SYNTH_LEAGUE = League.SERIE_A

TEAMS: list[str] = [
    "Alpha",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
    "Golf",
    "Hotel",
]


@pytest.fixture()
def tmp_lake(tmp_path: Path) -> Lake:
    lake = Lake(root=tmp_path / "lake")
    lake.ensure_schema()
    return lake


@pytest.fixture()
def synth_matches() -> list[Match]:
    """Deterministic double round-robin (56 matches)."""
    matches: list[Match] = []
    rng = random.Random(1234)
    day = date(2023, 8, 1)
    ingested = datetime(2024, 6, 1, tzinfo=UTC)
    for round_idx, (home, away) in enumerate(_double_round_robin(TEAMS)):
        match_date = day + timedelta(days=round_idx * 3)
        home_goals = rng.randint(0, 4)
        away_goals = rng.randint(0, 3)
        mid = compute_match_id(home, away, match_date, SYNTH_LEAGUE)
        matches.append(
            Match(
                match_id=mid,
                league=SYNTH_LEAGUE,
                season=SYNTH_SEASON,
                match_date=match_date,
                home_team=home,
                away_team=away,
                home_goals=home_goals,
                away_goals=away_goals,
                source="synthetic",
                ingested_at=ingested,
            )
        )
    return matches


@pytest.fixture()
def synth_stats(synth_matches: list[Match]) -> list[TeamMatchStats]:
    """One row per (match, team) with reproducible team-style stats."""
    rng = random.Random(9876)
    ingested = datetime(2024, 6, 1, tzinfo=UTC)
    stats: list[TeamMatchStats] = []
    style_seed = {team: rng.gauss(0, 1) for team in TEAMS}

    for m in synth_matches:
        for team, opponent, is_home, goals in (
            (m.home_team, m.away_team, True, m.home_goals),
            (m.away_team, m.home_team, False, m.away_goals),
        ):
            bias = style_seed[team] - style_seed[opponent]
            stats.append(
                TeamMatchStats(
                    match_id=m.match_id,
                    team=team,
                    is_home=is_home,
                    league=m.league,
                    season=m.season,
                    match_date=m.match_date,
                    goals=int(goals or 0),
                    goals_conceded=(m.away_goals if is_home else m.home_goals) or 0,
                    shots=_pos(12 + 2 * bias + rng.gauss(0, 2)),
                    shots_on_target=_pos(5 + bias + rng.gauss(0, 1.2)),
                    shots_off_target=_pos(7 + bias + rng.gauss(0, 1.2)),
                    corners=_pos(5 + bias + rng.gauss(0, 1.6)),
                    fouls=_pos(11 + rng.gauss(0, 2)),
                    yellow_cards=_pos(2 + rng.gauss(0, 1)),
                    red_cards=0,
                    possession_pct=float(50 + 10 * bias + rng.gauss(0, 3)),
                    source="synthetic",
                    ingested_at=ingested,
                )
            )
    return stats


@pytest.fixture()
def seeded_lake(
    tmp_lake: Lake,
    synth_matches: list[Match],
    synth_stats: list[TeamMatchStats],
) -> Lake:
    prov = IngestProvenance(
        source="synthetic",
        run_id="test-run",
        actor="test",
        captured_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    tmp_lake.ingest_matches(synth_matches, provenance=prov)
    tmp_lake.ingest_team_match_stats(synth_stats, provenance=prov)
    return tmp_lake


@pytest.fixture()
def upcoming_fixture(synth_matches: list[Match]) -> Match:
    """Match near the end of the season, after enough history is available."""
    return synth_matches[-2]


def make_odds_snapshots(
    fixture: Match,
    *,
    bookmaker: Bookmaker = Bookmaker.SISAL,
    captured_at: datetime | None = None,
) -> list[OddsSnapshot]:
    """Deterministic odds across several markets for a fixture."""
    if captured_at is None:
        captured_at = datetime.combine(
            fixture.match_date, datetime.min.time(), tzinfo=UTC
        ) - timedelta(hours=6)
    base = {
        "bookmaker": bookmaker,
        "bookmaker_event_id": f"evt-{fixture.match_id}",
        "match_id": fixture.match_id,
        "match_label": f"{fixture.home_team}-{fixture.away_team}",
        "match_date": fixture.match_date,
        "season": fixture.season,
        "league": fixture.league,
        "home_team": fixture.home_team,
        "away_team": fixture.away_team,
        "captured_at": captured_at,
        "source": "synthetic",
        "run_id": "test",
    }
    snaps: list[OddsSnapshot] = []

    for sel, payout in (("OVER", 1.85), ("UNDER", 1.95)):
        snaps.append(
            OddsSnapshot(
                market=Market.GOALS_OVER_UNDER,
                market_params={"threshold": 2.5},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    for sel, payout in (("OVER", 1.80), ("UNDER", 2.00)):
        snaps.append(
            OddsSnapshot(
                market=Market.CORNER_TOTAL,
                market_params={"threshold": 9.5},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    for sel, payout in (("1", 2.20), ("X", 3.20), ("2", 3.00)):
        snaps.append(
            OddsSnapshot(
                market=Market.MATCH_1X2,
                market_params={},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    for sel, payout in (("YES", 1.75), ("NO", 2.05)):
        snaps.append(
            OddsSnapshot(
                market=Market.GOALS_BOTH_TEAMS,
                market_params={},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    return snaps


def ingest_odds(lake: Lake, snapshots: list[OddsSnapshot]) -> None:
    prov = IngestProvenance(
        source="synthetic",
        run_id="test",
        actor="test",
        captured_at=datetime.now(tz=UTC),
    )
    lake.ingest_odds(snapshots, provenance=prov)


def _double_round_robin(teams: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for i, home in enumerate(teams):
        for away in teams[i + 1 :]:
            pairs.append((home, away))
            pairs.append((away, home))
    return pairs


def _pos(value: float) -> int:
    return max(0, round(value))


def synthetic_stats_frame() -> pl.DataFrame:
    """Tiny 4-team, 6-match frame used by isolated unit tests."""
    rows: list[dict[str, Any]] = []
    pairs = [("A", "B"), ("B", "A"), ("A", "C"), ("C", "A"), ("B", "D"), ("D", "B")]
    for day, (home, away) in enumerate(pairs):
        match_date = date(2023, 9, 1) + timedelta(days=day)
        mid = hashlib.sha256(f"{home}|{away}|{day}".encode()).hexdigest()[:16]
        for team, opp, is_home in ((home, away, True), (away, home, False)):
            rows.append(
                {
                    "match_id": mid,
                    "team": team,
                    "opponent": opp,
                    "is_home": is_home,
                    "league": "serie_a",
                    "season": "2023-24",
                    "match_date": match_date,
                    "goals": 2 if team == home else 1,
                    "corners": 6 if team == "A" else (4 if team == "B" else 3),
                    "shots": 10,
                    "shots_on_target": 4,
                    "yellow_cards": 2,
                    "fouls": 10,
                    "goals_conceded": 1 if team == home else 2,
                }
            )
    return pl.DataFrame(rows)
