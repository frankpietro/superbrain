"""Shared fixtures for the Phase-5 scheduler tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League, OddsSnapshot
from superbrain.data.connection import Lake


def _make_snapshot(idx: int, captured_at: datetime) -> OddsSnapshot:
    return OddsSnapshot(
        bookmaker=Bookmaker.SISAL,
        bookmaker_event_id=f"event-{idx}",
        match_id=None,
        match_label=f"Home {idx} - Away {idx}",
        match_date=captured_at.date(),
        season="2025-26",
        league=League.SERIE_A,
        home_team=f"Home {idx}",
        away_team=f"Away {idx}",
        market=Market.MATCH_1X2,
        market_params={},
        selection="1",
        payout=1.5 + idx * 0.1,
        captured_at=captured_at,
        source="test",
        run_id="test-run",
    )


@pytest.fixture
def captured_at() -> datetime:
    return datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def synthetic_snapshots(captured_at: datetime) -> list[OddsSnapshot]:
    return [_make_snapshot(i, captured_at) for i in range(3)]


@pytest.fixture
def lake(tmp_path: Path) -> Iterator[Lake]:
    root = tmp_path / "lake"
    root.mkdir()
    lk = Lake(root=root)
    lk.ensure_schema()
    try:
        yield lk
    finally:
        lk.close()
