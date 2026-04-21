"""Tests for the :class:`Lake` lifecycle: ensure_schema, ingest, read."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from superbrain.core.markets import Market
from superbrain.core.models import (
    Bookmaker,
    IngestProvenance,
    League,
    Match,
    OddsSnapshot,
    ScrapeRun,
    TeamMatchStats,
    compute_match_id,
)
from superbrain.data.connection import Lake


@pytest.fixture()
def lake(tmp_path: Path) -> Lake:
    lk = Lake(tmp_path / "lake")
    lk.ensure_schema()
    return lk


def _snapshot(**overrides: Any) -> OddsSnapshot:
    base: dict[str, Any] = {
        "bookmaker": Bookmaker.SISAL,
        "bookmaker_event_id": "evt-1",
        "match_id": None,
        "match_label": "Roma-Lazio",
        "match_date": date(2024, 9, 1),
        "season": "2024-25",
        "league": League.SERIE_A,
        "home_team": "Roma",
        "away_team": "Lazio",
        "market": Market.CORNER_TOTAL,
        "market_params": {"threshold": 9.5},
        "selection": "OVER",
        "payout": 1.85,
        "captured_at": datetime(2024, 9, 1, 12, tzinfo=UTC),
        "source": "test",
        "run_id": "run-1",
    }
    base.update(overrides)
    return OddsSnapshot(**base)


def _provenance(**overrides: Any) -> IngestProvenance:
    base: dict[str, Any] = {
        "source": "test",
        "run_id": "run-1",
        "actor": "tests",
        "captured_at": datetime.now(tz=UTC),
    }
    base.update(overrides)
    return IngestProvenance(**base)


class TestEnsureSchema:
    def test_creates_table_roots(self, tmp_path: Path) -> None:
        lake = Lake(tmp_path / "lake")
        lake.ensure_schema()
        assert (tmp_path / "lake" / "odds").is_dir()
        assert (tmp_path / "lake" / "matches").is_dir()
        assert (tmp_path / "lake" / "team_match_stats").is_dir()
        assert (tmp_path / "lake" / "scrape_runs").is_dir()
        assert (tmp_path / "lake" / "simulation_runs").is_dir()

    def test_writes_manifest_with_applied_migrations(self, tmp_path: Path) -> None:
        lake = Lake(tmp_path / "lake")
        lake.ensure_schema()
        manifest = json.loads((tmp_path / "lake" / "schema_manifest.json").read_text())
        assert manifest["version"] >= 2
        versions = {m["version"] for m in manifest["applied_migrations"]}
        assert {1, 2}.issubset(versions)

    def test_idempotent(self, tmp_path: Path) -> None:
        lake = Lake(tmp_path / "lake")
        lake.ensure_schema()
        lake.ensure_schema()
        manifest = json.loads((tmp_path / "lake" / "schema_manifest.json").read_text())
        versions = [m["version"] for m in manifest["applied_migrations"]]
        # Each migration applied exactly once.
        assert len(versions) == len(set(versions))


class TestIngestOdds:
    def test_roundtrip_single_snapshot(self, lake: Lake) -> None:
        report = lake.ingest_odds([_snapshot()], provenance=_provenance())
        assert report.rows_received == 1
        assert report.rows_written == 1
        assert report.rows_skipped_duplicate == 0

        df = lake.read_odds(bookmaker="sisal")
        assert df.height == 1
        assert df.row(0, named=True)["payout"] == pytest.approx(1.85)

    def test_dedupes_on_natural_key(self, lake: Lake) -> None:
        s = _snapshot()
        r1 = lake.ingest_odds([s], provenance=_provenance())
        r2 = lake.ingest_odds([s], provenance=_provenance())
        assert r1.rows_written == 1
        assert r2.rows_written == 0
        assert r2.rows_skipped_duplicate == 1
        assert lake.read_odds().height == 1

    def test_different_capture_times_are_kept(self, lake: Lake) -> None:
        s1 = _snapshot()
        s2 = _snapshot(captured_at=datetime(2024, 9, 1, 13, tzinfo=UTC))
        lake.ingest_odds([s1, s2], provenance=_provenance())
        assert lake.read_odds().height == 2

    def test_within_batch_dedupe(self, lake: Lake) -> None:
        s = _snapshot()
        report = lake.ingest_odds([s, s, s], provenance=_provenance())
        assert report.rows_written == 1
        assert report.rows_skipped_duplicate == 2

    def test_partitioned_by_bookmaker_market_season(self, lake: Lake, tmp_path: Path) -> None:
        lake.ingest_odds(
            [
                _snapshot(bookmaker=Bookmaker.SISAL, market=Market.CORNER_TOTAL),
                _snapshot(
                    bookmaker=Bookmaker.GOLDBET,
                    bookmaker_event_id="g-1",
                    market=Market.GOALS_OVER_UNDER,
                    selection="UNDER",
                ),
            ],
            provenance=_provenance(),
        )
        sisal_dir = (
            tmp_path
            / "lake"
            / "odds"
            / "bookmaker=sisal"
            / "market=corner_total"
            / "season=2024-25"
        )
        goldbet_dir = (
            tmp_path
            / "lake"
            / "odds"
            / "bookmaker=goldbet"
            / "market=goals_over_under"
            / "season=2024-25"
        )
        assert any(sisal_dir.glob("*.parquet"))
        assert any(goldbet_dir.glob("*.parquet"))

    def test_empty_batch_is_noop(self, lake: Lake) -> None:
        report = lake.ingest_odds([], provenance=_provenance())
        assert report.rows_written == 0


class TestIngestMatchesAndStats:
    def _match(self) -> Match:
        match_id = compute_match_id("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A)
        return Match(
            match_id=match_id,
            league=League.SERIE_A,
            season="2024-25",
            match_date=date(2024, 9, 1),
            home_team="Roma",
            away_team="Lazio",
            home_goals=2,
            away_goals=1,
            source="test",
            ingested_at=datetime.now(tz=UTC),
        )

    def test_match_roundtrip(self, lake: Lake) -> None:
        report = lake.ingest_matches([self._match()], provenance=_provenance())
        assert report.rows_written == 1
        df = lake.read_matches(league="serie_a")
        assert df.height == 1
        assert df.row(0, named=True)["home_goals"] == 2

    def test_match_index_refreshed(self, lake: Lake) -> None:
        lake.ingest_matches([self._match()], provenance=_provenance())
        import polars as pl

        idx_path = lake.layout.matches_root / "match_index.parquet"
        assert idx_path.exists()
        idx = pl.read_parquet(idx_path)
        assert idx.height == 1
        assert set(idx.columns) == {
            "match_id",
            "league",
            "season",
            "match_date",
            "home_team",
            "away_team",
        }

    def test_stats_roundtrip(self, lake: Lake) -> None:
        match_id = compute_match_id("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A)
        stats = [
            TeamMatchStats(
                match_id=match_id,
                team="Roma",
                is_home=True,
                league=League.SERIE_A,
                season="2024-25",
                match_date=date(2024, 9, 1),
                goals=2,
                shots=14,
                corners=7,
                source="test",
                ingested_at=datetime.now(tz=UTC),
            ),
        ]
        report = lake.ingest_team_match_stats(stats, provenance=_provenance())
        assert report.rows_written == 1


class TestOddsPromotesFixtures:
    """`ingest_odds` populates `matches` for fixtures seen only via odds.

    Without this, the bookmaker scrapers (which only call ``ingest_odds``)
    leave the matches table empty for upcoming fixtures, so the
    ``/matches`` API shows zero rows even when the lake knows about the
    weekend's games.
    """

    @staticmethod
    def _snap(**overrides: Any) -> OddsSnapshot:
        match_id = compute_match_id(
            overrides.get("home_team", "Roma"),
            overrides.get("away_team", "Lazio"),
            overrides.get("match_date", date(2024, 9, 1)),
            overrides.get("league", League.SERIE_A),
        )
        return _snapshot(match_id=match_id, **overrides)

    def test_promotes_one_fixture_per_match_id(self, lake: Lake) -> None:
        s1 = self._snap()
        s2 = self._snap(
            selection="UNDER",
            market_params={"threshold": 10.5},
            captured_at=datetime(2024, 9, 1, 13, tzinfo=UTC),
        )
        lake.ingest_odds([s1, s2], provenance=_provenance())

        matches = lake.read_matches()
        assert matches.height == 1
        row = matches.row(0, named=True)
        assert row["match_id"] == s1.match_id
        assert row["home_team"] == "Roma"
        assert row["away_team"] == "Lazio"
        assert row["league"] == League.SERIE_A.value
        assert row["home_goals"] is None
        assert row["away_goals"] is None
        assert row["source"].startswith("odds:")

    def test_promotes_distinct_fixtures_separately(self, lake: Lake) -> None:
        s1 = self._snap()
        s2 = self._snap(
            bookmaker_event_id="evt-2",
            home_team="Milan",
            away_team="Inter",
            match_date=date(2024, 9, 2),
        )
        lake.ingest_odds([s1, s2], provenance=_provenance())
        assert lake.read_matches().height == 2

    def test_skips_snapshot_without_match_id(self, lake: Lake) -> None:
        lake.ingest_odds([_snapshot(match_id=None)], provenance=_provenance())
        assert lake.read_matches().height == 0

    def test_skips_snapshot_without_league(self, lake: Lake) -> None:
        match_id = compute_match_id("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A)
        lake.ingest_odds(
            [_snapshot(match_id=match_id, league=None)],
            provenance=_provenance(),
        )
        assert lake.read_matches().height == 0

    def test_does_not_overwrite_authoritative_match(self, lake: Lake) -> None:
        """Historical backfill lands first → odds-promotion is a no-op."""
        match_id = compute_match_id("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A)
        authoritative = Match(
            match_id=match_id,
            league=League.SERIE_A,
            season="2024-25",
            match_date=date(2024, 9, 1),
            home_team="Roma",
            away_team="Lazio",
            home_goals=2,
            away_goals=1,
            source="football_data",
            ingested_at=datetime.now(tz=UTC),
        )
        lake.ingest_matches([authoritative], provenance=_provenance())

        lake.ingest_odds([self._snap()], provenance=_provenance())

        matches = lake.read_matches()
        assert matches.height == 1
        row = matches.row(0, named=True)
        assert row["home_goals"] == 2
        assert row["source"] == "football_data"

    def test_idempotent_across_runs(self, lake: Lake) -> None:
        s = self._snap()
        lake.ingest_odds([s], provenance=_provenance())
        lake.ingest_odds(
            [self._snap(captured_at=datetime(2024, 9, 1, 14, tzinfo=UTC))],
            provenance=_provenance(),
        )
        assert lake.read_matches().height == 1


class TestLogScrapeRun:
    def test_writes_partition(self, lake: Lake, tmp_path: Path) -> None:
        run = ScrapeRun(
            run_id="run-xyz",
            bookmaker=Bookmaker.SISAL,
            scraper="sisal-live",
            started_at=datetime(2024, 9, 1, 12, tzinfo=UTC),
            finished_at=datetime(2024, 9, 1, 12, 1, tzinfo=UTC),
            status="success",
            rows_written=10,
            rows_rejected=0,
            host="worker-1",
        )
        partition = lake.log_scrape_run(run)
        assert partition.exists()
        assert any(partition.glob("*.parquet"))
