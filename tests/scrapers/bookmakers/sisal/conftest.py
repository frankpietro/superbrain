"""Shared fixtures for Sisal scraper tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "bookmakers" / "sisal"


def _load(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / name
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"expected JSON object in {name}, got {type(data).__name__}"
    return data


@pytest.fixture
def tree_payload() -> dict[str, Any]:
    return _load("tree.json")


@pytest.fixture
def serie_a_events_payload() -> dict[str, Any]:
    return _load("events-serie_a.json")


@pytest.fixture
def premier_events_payload() -> dict[str, Any]:
    return _load("events-premier_league.json")


@pytest.fixture
def bundesliga_events_payload() -> dict[str, Any]:
    return _load("events-bundesliga.json")


@pytest.fixture
def la_liga_events_payload() -> dict[str, Any]:
    return _load("events-la_liga.json")


@pytest.fixture
def ligue_1_events_payload() -> dict[str, Any]:
    return _load("events-ligue_1.json")


@pytest.fixture
def event_markets_payload() -> dict[str, Any]:
    return _load("markets-36171-19.json")
