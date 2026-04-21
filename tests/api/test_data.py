"""``/data/overview`` tests — empty lake and seeded lake shapes."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League
from superbrain.data.connection import Lake

from .conftest import make_match, make_scrape_run, make_snapshot, provenance


def test_overview_empty_lake(client: TestClient) -> None:
    resp = client.get("/data/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["lake_root"]
    assert "generated_at" in body
    table_names = [t["name"] for t in body["tables"]]
    assert table_names == [
        "matches",
        "team_match_stats",
        "odds",
        "team_elo",
        "scrape_runs",
        "simulation_runs",
    ]
    for table in body["tables"]:
        assert table["total_rows"] == 0
        assert table["partitions"] == []
        assert table["samples"] == []
        assert table["columns"] == []


def test_overview_reports_counts_schema_partitions_and_samples(
    client: TestClient, lake: Lake
) -> None:
    matches = [
        make_match(home="Roma", away="Lazio", match_date=date(2023, 9, 1)),
        make_match(home="Inter", away="Juventus", match_date=date(2023, 9, 2)),
        make_match(
            home="Arsenal",
            away="Chelsea",
            match_date=date(2024, 1, 1),
            league=League.PREMIER_LEAGUE,
            season="2023-24",
        ),
    ]
    lake.ingest_matches(matches, provenance=provenance())
    lake.ingest_odds(
        [
            make_snapshot(
                bookmaker=Bookmaker.SISAL,
                market=Market.CORNER_TOTAL,
                captured_at=datetime(2023, 9, 1, 12, tzinfo=UTC),
            ),
            make_snapshot(
                bookmaker=Bookmaker.GOLDBET,
                market=Market.MATCH_1X2,
                selection="HOME",
                captured_at=datetime(2023, 9, 1, 13, tzinfo=UTC),
            ),
        ],
        provenance=provenance(),
    )
    lake.log_scrape_run(make_scrape_run())

    resp = client.get("/data/overview")
    assert resp.status_code == 200
    body = resp.json()
    by_name = {t["name"]: t for t in body["tables"]}

    assert by_name["matches"]["total_rows"] == 3
    assert by_name["matches"]["exists"] is True
    match_partitions = {
        (p["values"]["league"], p["values"]["season"]): p["rows"]
        for p in by_name["matches"]["partitions"]
    }
    assert match_partitions[("serie_a", "2024-25")] == 2
    assert match_partitions[("premier_league", "2023-24")] == 1
    assert any(c["name"] == "match_id" for c in by_name["matches"]["columns"])
    assert 0 < len(by_name["matches"]["samples"]) <= 5
    sample = by_name["matches"]["samples"][0]
    assert isinstance(sample["match_id"], str)

    assert by_name["odds"]["total_rows"] == 2
    odds_partition_keys = by_name["odds"]["partition_keys"]
    assert odds_partition_keys == ["bookmaker", "market", "season"]
    odds_partitions = {
        (p["values"]["bookmaker"], p["values"]["market"]): p["rows"]
        for p in by_name["odds"]["partitions"]
    }
    assert odds_partitions[("sisal", "corner_total")] == 1
    assert odds_partitions[("goldbet", "match_1x2")] == 1

    assert by_name["scrape_runs"]["total_rows"] == 1
