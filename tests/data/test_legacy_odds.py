"""Tests for the legacy odds mapper."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from superbrain.core.markets import Market
from superbrain.data.legacy_odds import (
    LegacyOddsImportError,
    legacy_row_to_snapshot,
    legacy_rows_to_snapshots,
)


def _make_legacy_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE odds_corner_total (
            date TEXT, season TEXT, match TEXT, bookmaker TEXT,
            threshold REAL, bet TEXT, payout REAL
        );
        CREATE TABLE odds_corner_combo (
            date TEXT, season TEXT, match TEXT, bookmaker TEXT,
            threshold_1 REAL, threshold_2 REAL, bet TEXT, payout REAL
        );
        CREATE TABLE odds_corner_first_to (
            date TEXT, season TEXT, match TEXT, bookmaker TEXT,
            target_corners INTEGER, bet TEXT, payout REAL
        );
        CREATE TABLE odds_goals_over_under (
            date TEXT, season TEXT, match TEXT, bookmaker TEXT,
            threshold REAL, bet TEXT, payout REAL
        );
        """
    )
    conn.executemany(
        "INSERT INTO odds_corner_total VALUES (?,?,?,?,?,?,?)",
        [
            ("15/08/2025", "2526", "Girona-Rayo Vallecano", "sisal", 9.5, "OVER", 1.85),
            ("15/08/2025", "2526", "Girona-Rayo Vallecano", "sisal", 9.5, "UNDER", 1.95),
            ("", "2526", "", "sisal", None, None, 0.0),  # empty row -> filtered
        ],
    )
    conn.executemany(
        "INSERT INTO odds_corner_combo VALUES (?,?,?,?,?,?,?,?)",
        [
            ("15/08/2025", "2526", "Girona-Rayo", "sisal", 2.5, 2.5, "OVER+OVER", 1.3),
        ],
    )
    conn.executemany(
        "INSERT INTO odds_corner_first_to VALUES (?,?,?,?,?,?,?)",
        [
            ("15/08/2025", "2526", "Girona-Rayo", "sisal", 5, "HOME", 2.1),
        ],
    )
    conn.executemany(
        "INSERT INTO odds_goals_over_under VALUES (?,?,?,?,?,?,?)",
        [
            ("20/08/2025", "2526", "Siviglia-Barcellona", "sisal", 2.5, "OVER", 1.70),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def legacy_db(tmp_path: Path) -> Path:
    db = tmp_path / "legacy.db"
    _make_legacy_db(db)
    return db


class TestLegacyRowToSnapshot:
    def test_corner_total_maps_cleanly(self) -> None:
        row = {
            "date": "15/08/2025",
            "season": "2526",
            "match": "Girona-Rayo Vallecano",
            "bookmaker": "sisal",
            "threshold": 9.5,
            "bet": "OVER",
            "payout": 1.85,
        }
        s = legacy_row_to_snapshot("odds_corner_total", row, run_id="run-1")
        assert s.market is Market.CORNER_TOTAL
        assert s.selection == "OVER"
        assert s.payout == pytest.approx(1.85)
        assert s.market_params == {"threshold": 9.5}
        assert s.season == "2025-26"

    def test_team_names_canonicalized(self) -> None:
        row = {
            "date": "20/08/2025",
            "season": "2526",
            "match": "Siviglia-Barcellona",
            "bookmaker": "sisal",
            "threshold": 2.5,
            "bet": "OVER",
            "payout": 1.7,
        }
        s = legacy_row_to_snapshot("odds_goals_over_under", row, run_id="r")
        assert s.home_team == "Sevilla"
        assert s.away_team == "Barcelona"
        assert s.match_label == "Sevilla-Barcelona"

    def test_unknown_table_rejected(self) -> None:
        row = {
            "date": "20/08/2025",
            "season": "2526",
            "match": "a-b",
            "bookmaker": "sisal",
            "bet": "1",
            "payout": 1.0,
        }
        with pytest.raises(LegacyOddsImportError):
            legacy_row_to_snapshot("odds_unknown", row, run_id="r")

    def test_unknown_bookmaker_rejected(self) -> None:
        row = {
            "date": "20/08/2025",
            "season": "2526",
            "match": "a-b",
            "bookmaker": "megabet",
            "threshold": 2.5,
            "bet": "OVER",
            "payout": 1.7,
        }
        with pytest.raises(LegacyOddsImportError):
            legacy_row_to_snapshot("odds_goals_over_under", row, run_id="r")

    def test_zero_payout_rejected(self) -> None:
        row = {
            "date": "20/08/2025",
            "season": "2526",
            "match": "a-b",
            "bookmaker": "sisal",
            "threshold": 2.5,
            "bet": "OVER",
            "payout": 0.0,
        }
        with pytest.raises(LegacyOddsImportError):
            legacy_row_to_snapshot("odds_goals_over_under", row, run_id="r")


class TestLegacyRowsToSnapshots:
    def test_full_fixture_counts(self, legacy_db: Path) -> None:
        snapshots, rejected = legacy_rows_to_snapshots(str(legacy_db))
        # Two valid corner_total rows + one combo + one first_to + one OU = 5
        assert len(snapshots) == 5
        assert sum(rejected.values()) == 0

    def test_only_tables_restriction(self, legacy_db: Path) -> None:
        snapshots, _ = legacy_rows_to_snapshots(
            str(legacy_db), only_tables=["odds_corner_total"]
        )
        assert len(snapshots) == 2
        assert all(s.market.value == "corner_total" for s in snapshots)
