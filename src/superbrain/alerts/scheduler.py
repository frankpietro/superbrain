"""Scheduler entry-point used by Phase-5 APScheduler and the GH Actions fallback.

The only public function — :func:`run_alert_sweep` — pulls the latest
pipeline results for live + upcoming matches in the next
``settings.alert_lookahead_hours`` hours and feeds them into the
dispatcher. Phase 5 owns the *when*; we only ship the *what*.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import polars as pl

from superbrain.alerts.config import AlertSettings
from superbrain.alerts.dispatcher import AlertDispatcher, AlertRunReport
from superbrain.core.models import League, Match
from superbrain.engine.pipeline import find_value_bets

if TYPE_CHECKING:
    from superbrain.data.connection import Lake
    from superbrain.engine.pipeline import ValueBet

logger = logging.getLogger(__name__)


async def run_alert_sweep(
    lake: Lake,
    *,
    settings: AlertSettings | None = None,
    dispatcher: AlertDispatcher | None = None,
    now: datetime | None = None,
    value_bets: Iterable[ValueBet] | None = None,
) -> AlertRunReport:
    """One alert sweep over the next ``lookahead`` hours of fixtures.

    The default call (``run_alert_sweep(lake)``) reads fixtures from the
    lake and prices them via
    :func:`~superbrain.engine.pipeline.find_value_bets`. Callers can
    bypass that — the scheduler may already have priced results cached —
    by supplying ``value_bets`` directly.

    :param lake: lake handle backing the data.
    :param settings: override alert settings (defaults to env).
    :param dispatcher: pre-built dispatcher (tests inject this).
    :param now: override the clock for deterministic sweeps.
    :param value_bets: override the pricing step — useful for tests
        and for APScheduler jobs that share a priced cache across
        alert + SPA calls.
    :return: :class:`AlertRunReport` returned by
        :meth:`AlertDispatcher.dispatch`.
    """
    settings = settings or AlertSettings()
    now = now or datetime.now(tz=UTC)
    dispatcher = dispatcher or AlertDispatcher.from_settings(settings)

    if value_bets is None:
        value_bets = _collect_value_bets(lake, settings=settings, now=now)
    value_bets_list = list(value_bets)

    logger.info(
        "alerts.run_sweep lookahead_hours=%d fixtures_priced=%d",
        settings.alert_lookahead_hours,
        len(value_bets_list),
    )
    return await dispatcher.dispatch(value_bets_list)


def _collect_value_bets(lake: Lake, *, settings: AlertSettings, now: datetime) -> list[ValueBet]:
    """Walk upcoming fixtures and price them one by one."""
    fixtures = _find_upcoming_fixtures(
        lake, now=now, lookahead_hours=settings.alert_lookahead_hours
    )
    if not fixtures:
        return []

    collected: list[ValueBet] = []
    for fixture in fixtures:
        try:
            bets = find_value_bets(
                lake,
                fixture=fixture,
                edge_threshold=settings.alert_edge_threshold,
            )
        except Exception:
            logger.exception("alerts.run_sweep failed to price fixture %s", fixture.match_id)
            continue
        collected.extend(bets)
    return collected


def _find_upcoming_fixtures(lake: Lake, *, now: datetime, lookahead_hours: int) -> list[Match]:
    """Read ``matches`` rows whose match_date falls in ``[today, today+lookahead]``.

    We intentionally include the fixture's date without a time-of-day
    component: the lake stores ``match_date`` only. ``lookahead_hours``
    rounds up to the nearest day for the filter.
    """
    today = now.astimezone(UTC).date()
    horizon = (now + timedelta(hours=lookahead_hours)).astimezone(UTC).date()
    df = lake.read_matches(since=today)
    if df.is_empty():
        return []

    df = df.filter(pl.col("match_date") <= horizon)
    if df.is_empty():
        return []

    fixtures: list[Match] = []
    for row in df.iter_rows(named=True):
        match = _row_to_match(row)
        if match is not None:
            fixtures.append(match)
    return fixtures


def _row_to_match(row: dict[str, Any]) -> Match | None:
    league_value = row.get("league")
    try:
        league = League(league_value) if league_value is not None else None
    except ValueError:
        return None
    if league is None:
        return None

    match_date = row.get("match_date")
    if not isinstance(match_date, date):
        return None

    ingested_at = row.get("ingested_at")
    if isinstance(ingested_at, datetime) and ingested_at.tzinfo is None:
        ingested_at = ingested_at.replace(tzinfo=UTC)
    elif ingested_at is None:
        ingested_at = datetime.now(tz=UTC)

    try:
        return Match(
            match_id=row["match_id"],
            league=league,
            season=row["season"],
            match_date=match_date,
            home_team=row["home_team"],
            away_team=row["away_team"],
            home_goals=row.get("home_goals"),
            away_goals=row.get("away_goals"),
            source=row.get("source", "lake"),
            ingested_at=ingested_at,
        )
    except (KeyError, ValueError):
        return None
