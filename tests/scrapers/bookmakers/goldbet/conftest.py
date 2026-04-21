"""Shared fixtures for the Goldbet scraper test-suite."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from superbrain.core.models import League
from superbrain.scrapers.bookmakers.goldbet.markets import EventMeta, build_event_meta

FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "bookmakers" / "goldbet"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_ROOT / name).read_text("utf-8"))


@pytest.fixture
def events_serie_a() -> dict[str, Any]:
    return _load("events_serie_a.json")


@pytest.fixture
def markets_tab0() -> dict[str, Any]:
    return _load("markets_tab0.json")


@pytest.fixture
def markets_tab_angoli() -> dict[str, Any]:
    return _load("markets_tab_angoli.json")


@pytest.fixture
def markets_tab_tree() -> dict[str, Any]:
    return _load("markets_tab_tree.json")


@pytest.fixture
def markets_tab_multigol() -> dict[str, Any]:
    return _load("markets_tab_multigol.json")


@pytest.fixture
def captured_at() -> datetime:
    return datetime(2026, 4, 21, 16, 40, 46, tzinfo=UTC)


@pytest.fixture
def event_meta(markets_tab0: dict[str, Any], captured_at: datetime) -> EventMeta:
    meta = build_event_meta(
        markets_tab0["leo"][0],
        captured_at=captured_at,
        source="goldbet-test",
        run_id="test-run",
        league_hint=League.SERIE_A,
    )
    assert meta is not None
    return meta


@pytest.fixture
def fixtures_root() -> Path:
    return FIXTURES_ROOT


@pytest.fixture
def tmp_lake_root(tmp_path: Path) -> Iterator[Path]:
    """Temporary DuckDB/Parquet lake root for ingest tests."""
    root = tmp_path / "lake"
    root.mkdir()
    yield root
