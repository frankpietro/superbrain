"""Shared fixtures for the API test suite."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from superbrain.api.app import create_app
from superbrain.api.config import Settings
from superbrain.core.markets import Market
from superbrain.core.models import (
    Bookmaker,
    IngestProvenance,
    League,
    Match,
    OddsSnapshot,
    ScrapeRun,
    compute_match_id,
)
from superbrain.data.connection import Lake


@pytest.fixture()
def token() -> str:
    return "test-token"


@pytest.fixture()
def settings(tmp_path: Path, token: str) -> Settings:
    return Settings(
        SUPERBRAIN_LAKE_PATH=tmp_path / "lake",
        SUPERBRAIN_API_TOKENS=(token, "other-token"),
        SUPERBRAIN_CORS_ORIGINS=("http://localhost:5273",),
        SUPERBRAIN_LOG_LEVEL="WARNING",
    )


@pytest.fixture()
def lake(settings: Settings) -> Lake:
    lk = Lake(settings.lake_path)
    lk.ensure_schema()
    return lk


@pytest.fixture()
def app(settings: Settings, lake: Lake) -> FastAPI:
    return create_app(settings=settings, lake=lake)


@pytest.fixture()
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_match(
    home: str = "Roma",
    away: str = "Lazio",
    match_date: date = date(2024, 9, 1),
    league: League = League.SERIE_A,
    season: str = "2024-25",
) -> Match:
    match_id = compute_match_id(home, away, match_date, league)
    return Match(
        match_id=match_id,
        league=league,
        season=season,
        match_date=match_date,
        home_team=home,
        away_team=away,
        source="tests",
        ingested_at=datetime(2024, 9, 1, 10, tzinfo=UTC),
    )


def make_snapshot(**overrides: Any) -> OddsSnapshot:
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


def provenance() -> IngestProvenance:
    return IngestProvenance(
        source="tests",
        run_id="run-1",
        actor="pytest",
        captured_at=datetime(2024, 9, 1, 12, tzinfo=UTC),
        bookmaker=Bookmaker.SISAL,
    )


def make_scrape_run(
    *,
    run_id: str = "run-1",
    bookmaker: Bookmaker | None = Bookmaker.SISAL,
    scraper: str = "sisal.prematch",
    started_at: datetime = datetime(2024, 9, 1, 12, tzinfo=UTC),
    status: str = "ok",
    rows_written: int = 10,
) -> ScrapeRun:
    return ScrapeRun(
        run_id=run_id,
        bookmaker=bookmaker,
        scraper=scraper,
        started_at=started_at,
        finished_at=started_at,
        status=status,
        rows_written=rows_written,
        rows_rejected=0,
        error_message=None,
        host="tests",
    )
