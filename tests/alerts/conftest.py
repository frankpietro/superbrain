"""Shared fixtures for the alert-pipeline tests.

We never ship real value bets through these tests; a tiny factory builds
:class:`ValueBet` objects on demand, stubs included, so that every
policy / channel / dispatcher test is deterministic and free of
pipeline-math noise.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

import pytest

from superbrain.alerts.config import AlertSettings
from superbrain.core.markets import Market
from superbrain.core.models import League, Match, compute_match_id
from superbrain.engine.bets.base import Outcome
from superbrain.engine.pipeline import PricedOutcome, ValueBet


@pytest.fixture()
def default_settings(tmp_path: Any) -> AlertSettings:
    """An :class:`AlertSettings` with the sink pointed at a tmp file."""
    return AlertSettings(
        SUPERBRAIN_ALERT_SINK_PATH=tmp_path / "sent_alerts.parquet",
        SUPERBRAIN_ALERT_EDGE_THRESHOLD=0.05,
        SUPERBRAIN_ALERT_MIN_PROBABILITY=0.35,
        SUPERBRAIN_ALERT_MAX_PER_RUN=20,
        SUPERBRAIN_ALERT_PER_MATCH_CAP=3,
        SUPERBRAIN_ALERT_DEDUP_HOURS=24,
        SUPERBRAIN_ALERT_LOOKAHEAD_HOURS=48,
        SUPERBRAIN_ALERT_CONCURRENCY=4,
    )


def make_match(
    *,
    home: str = "Alpha",
    away: str = "Bravo",
    match_date: date = date(2025, 5, 18),
    league: League = League.SERIE_A,
    season: str = "2024-25",
) -> Match:
    mid = compute_match_id(home, away, match_date, league)
    return Match(
        match_id=mid,
        league=league,
        season=season,
        match_date=match_date,
        home_team=home,
        away_team=away,
        home_goals=None,
        away_goals=None,
        source="test",
        ingested_at=datetime(2025, 5, 15, tzinfo=UTC),
    )


def make_value_bet(
    *,
    fixture: Match | None = None,
    edge: float = 0.12,
    probability: float = 0.60,
    odds: float = 2.00,
    bookmaker: str = "sisal",
    market: Market = Market.GOALS_OVER_UNDER,
    selection: str = "OVER",
    params: Mapping[str, Any] | None = None,
    captured_at: datetime | None = None,
    label: str | None = "Goals over/under",
) -> ValueBet:
    """Build a synthetic :class:`ValueBet` with full provenance."""
    fixture = fixture or make_match()
    if params is None:
        params = {"threshold": 2.5} if market == Market.GOALS_OVER_UNDER else {}
    outcome = Outcome(market=market, selection=selection, params=dict(params), label=label)
    priced = PricedOutcome(
        fixture=fixture,
        outcome=outcome,
        model_probability=probability,
        model_payout=1.0 / probability if probability > 0 else 10000.0,
        sample_size=12,
        target_columns=["goals"],
    )
    if captured_at is None:
        captured_at = datetime(2025, 5, 17, 18, 0, tzinfo=UTC)
    return ValueBet(
        fixture=fixture,
        priced=priced,
        bookmaker=bookmaker,
        decimal_odds=odds,
        book_probability=1.0 / odds,
        edge=edge,
        captured_at=captured_at,
    )
