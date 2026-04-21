"""End-to-end: legacy SQLite -> Lake via the snapshot pipeline."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from superbrain.core.models import IngestProvenance
from superbrain.data.connection import Lake
from superbrain.data.legacy_odds import legacy_rows_to_snapshots


@pytest.fixture()
def legacy_db(tmp_path: Path) -> Path:
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE odds_corner_total (
            date TEXT, season TEXT, match TEXT, bookmaker TEXT,
            threshold REAL, bet TEXT, payout REAL
        );
        """
    )
    rows = [
        ("15/08/2025", "2526", "Girona-Rayo Vallecano", "sisal", 9.5, "OVER", 1.85),
        ("15/08/2025", "2526", "Girona-Rayo Vallecano", "sisal", 9.5, "UNDER", 1.95),
        ("15/08/2025", "2526", "Siviglia-Barcellona", "sisal", 9.5, "OVER", 1.78),
    ]
    conn.executemany("INSERT INTO odds_corner_total VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return db


def test_end_to_end_import(tmp_path: Path, legacy_db: Path) -> None:
    lake = Lake(tmp_path / "lake")
    lake.ensure_schema()

    from datetime import datetime, timezone

    snapshots, rejected = legacy_rows_to_snapshots(str(legacy_db), run_id="r-e2e")
    assert len(snapshots) == 3
    assert sum(rejected.values()) == 0

    provenance = IngestProvenance(
        source="legacy_sqlite",
        run_id="r-e2e",
        actor="test",
        captured_at=datetime.now(tz=timezone.utc),
    )
    report = lake.ingest_odds(snapshots, provenance=provenance)
    assert report.rows_received == 3
    assert report.rows_written == 3

    df = lake.read_odds(bookmaker="sisal", market="corner_total")
    assert df.height == 3
    # Team names should be canonicalized.
    teams = set(df.get_column("home_team").to_list()) | set(
        df.get_column("away_team").to_list()
    )
    assert "Sevilla" in teams
    assert "Barcelona" in teams
    assert "Siviglia" not in teams
