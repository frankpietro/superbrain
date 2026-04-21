"""End-to-end tests for :func:`superbrain.scrapers.bookmakers.sisal.scrape`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import pytest
import respx

from superbrain.core.models import Bookmaker, League
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.sisal.client import SISAL_PREMATCH_BASE
from superbrain.scrapers.bookmakers.sisal.scraper import (
    SISAL_LEAGUE_KEYS,
    reset_tree_cache,
    scrape,
)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    reset_tree_cache()


@pytest.fixture
def lake(tmp_path: Path) -> Lake:
    root = tmp_path / "lake"
    lk = Lake(root=root)
    lk.ensure_schema()
    return lk


def _route_all(
    tree_payload: dict[str, Any],
    events_by_league: dict[str, dict[str, Any]],
    event_markets_payload: dict[str, Any],
) -> None:
    respx.get(f"{SISAL_PREMATCH_BASE}/alberaturaPrematch").mock(
        return_value=httpx.Response(200, json=tree_payload)
    )
    for league, key in SISAL_LEAGUE_KEYS.items():
        payload = events_by_league.get(league.value, {"avvenimentoFeList": []})
        respx.get(f"{SISAL_PREMATCH_BASE}/v1/schedaManifestazione/0/{key}").mock(
            return_value=httpx.Response(200, json=payload)
        )
        for event in payload.get("avvenimentoFeList", []):
            event_key = event["key"]
            respx.get(f"{SISAL_PREMATCH_BASE}/schedaAvvenimento/{event_key}").mock(
                return_value=httpx.Response(200, json=event_markets_payload)
            )


@pytest.mark.asyncio
@respx.mock
async def test_end_to_end_scrape_writes_rows(
    lake: Lake,
    tree_payload: dict[str, Any],
    serie_a_events_payload: dict[str, Any],
    event_markets_payload: dict[str, Any],
) -> None:
    _route_all(
        tree_payload=tree_payload,
        events_by_league={"serie_a": serie_a_events_payload},
        event_markets_payload=event_markets_payload,
    )
    result = await scrape(lake, leagues=[League.SERIE_A], event_concurrency=2)
    assert result.status == "success"
    assert result.rows_written > 0
    assert result.per_league_events["serie_a"] == len(serie_a_events_payload["avvenimentoFeList"])
    # All 14 required market families present in the payload end up landing.
    assert result.per_market_rows["match_1x2"] > 0
    assert result.per_market_rows["goals_over_under"] > 0


@pytest.mark.asyncio
@respx.mock
async def test_idempotent_second_scrape_emits_zero_new_rows(
    lake: Lake,
    tree_payload: dict[str, Any],
    serie_a_events_payload: dict[str, Any],
    event_markets_payload: dict[str, Any],
) -> None:
    _route_all(
        tree_payload=tree_payload,
        events_by_league={"serie_a": serie_a_events_payload},
        event_markets_payload=event_markets_payload,
    )
    first = await scrape(lake, leagues=[League.SERIE_A], event_concurrency=2, run_id="run-1")
    assert first.rows_written > 0

    # Same captured_at + run_id ⇒ same natural key ⇒ every row dedupes.
    second = await scrape(
        lake,
        leagues=[League.SERIE_A],
        event_concurrency=2,
        run_id="run-1",
        captured_at=first.started_at,
    )
    assert second.rows_received > 0
    assert second.rows_written == 0
    assert second.ingest_report is not None
    assert second.ingest_report.rows_skipped_duplicate == second.ingest_report.rows_received


@pytest.mark.asyncio
@respx.mock
async def test_scrape_survives_league_failure(
    lake: Lake,
    tree_payload: dict[str, Any],
    serie_a_events_payload: dict[str, Any],
    event_markets_payload: dict[str, Any],
) -> None:
    _route_all(
        tree_payload=tree_payload,
        events_by_league={"serie_a": serie_a_events_payload},
        event_markets_payload=event_markets_payload,
    )
    # Override the Premier League route to always return 500 (even after retries).
    respx.get(
        f"{SISAL_PREMATCH_BASE}/v1/schedaManifestazione/0/{SISAL_LEAGUE_KEYS[League.PREMIER_LEAGUE]}"
    ).mock(return_value=httpx.Response(500, text="boom"))

    result = await scrape(
        lake,
        leagues=[League.SERIE_A, League.PREMIER_LEAGUE],
        event_concurrency=2,
    )
    # We still land Serie A rows; Premier failed but did not abort the run.
    assert result.rows_written > 0
    assert result.status == "partial"
    assert any(err.startswith("events:premier_league") for err in result.errors)


@pytest.mark.asyncio
@respx.mock
async def test_scrape_writes_scrape_run_log(
    lake: Lake,
    tree_payload: dict[str, Any],
    serie_a_events_payload: dict[str, Any],
    event_markets_payload: dict[str, Any],
) -> None:
    _route_all(
        tree_payload=tree_payload,
        events_by_league={"serie_a": serie_a_events_payload},
        event_markets_payload=event_markets_payload,
    )
    result = await scrape(lake, leagues=[League.SERIE_A], event_concurrency=2)

    run_files = list(lake.layout.scrape_runs_root.rglob("*.parquet"))
    assert run_files, "expected at least one scrape_runs parquet file"
    runs = pl.read_parquet(run_files)
    assert result.run_id in runs["run_id"].to_list()
    row = runs.filter(pl.col("run_id") == result.run_id).to_dicts()[0]
    assert row["bookmaker"] == Bookmaker.SISAL.value
    assert row["rows_written"] == result.rows_written


@pytest.mark.asyncio
@respx.mock
async def test_tree_cache_avoids_second_fetch(
    lake: Lake,
    tree_payload: dict[str, Any],
    serie_a_events_payload: dict[str, Any],
    event_markets_payload: dict[str, Any],
) -> None:
    tree_route = respx.get(f"{SISAL_PREMATCH_BASE}/alberaturaPrematch").mock(
        return_value=httpx.Response(200, json=tree_payload)
    )
    for key in SISAL_LEAGUE_KEYS.values():
        respx.get(f"{SISAL_PREMATCH_BASE}/v1/schedaManifestazione/0/{key}").mock(
            return_value=httpx.Response(200, json={"avvenimentoFeList": []})
        )
    await scrape(lake, leagues=[League.SERIE_A])
    await scrape(lake, leagues=[League.SERIE_A])
    assert tree_route.call_count == 1


def test_fixtures_are_under_50kb() -> None:
    """Sanity check on fixture hygiene."""
    fixture_dir = Path(__file__).resolve().parents[3] / "fixtures" / "bookmakers" / "sisal"
    for path in fixture_dir.glob("*.json"):
        size = path.stat().st_size
        assert size < 50 * 1024, f"{path.name} is {size} bytes (>50KB budget)"
        # Sanity check: must be valid JSON.
        json.loads(path.read_text(encoding="utf-8"))
