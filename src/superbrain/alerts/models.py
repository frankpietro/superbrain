"""Typed records flowing through the alert pipeline.

``AlertRecord`` is the canonical unit of work. It's derived deterministically
from a :class:`~superbrain.engine.pipeline.ValueBet`; the mapping is
one-way and idempotent so that the same value bet always maps to the same
``alert_id``.

The other dataclasses are pure view-types: they carry no logic, only
serialise well to parquet (``AlertSink``) and to the ``AlertRunReport``
summary returned by the dispatcher.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from superbrain.engine.pipeline import ValueBet


def bet_code_from_market(market: str, params: dict[str, object]) -> str:
    """Stable short code for a ``(market, params)`` tuple.

    The bookmaker + selection plus this code is enough to uniquely
    identify a value bet within a fixture: the params hash disambiguates
    e.g. Over 1.5 from Over 2.5 in the same ``goals_over_under`` market.

    :param market: market code string (e.g. ``"goals_over_under"``).
    :param params: ``Outcome.params`` dict.
    :return: ``"<market>"`` if params is empty, otherwise ``"<market>:<8h>"``.
    """
    if not params:
        return market
    payload = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:8]
    return f"{market}:{digest}"


def compute_alert_id(
    *,
    bet_code: str,
    match_id: str,
    bookmaker: str,
    selection: str,
    kickoff: datetime,
) -> str:
    """Hash of the natural key — stable across re-runs inside one calendar day.

    :param bet_code: see :func:`bet_code_from_market`.
    :param match_id: :class:`~superbrain.core.models.Match.match_id`.
    :param bookmaker: bookmaker slug.
    :param selection: canonical selection label (``"1"``, ``"OVER"``, …).
    :param kickoff: UTC kickoff datetime; only the date part enters the key.
    :return: 16-char hex digest.
    """
    kickoff_date = kickoff.date().isoformat()
    payload = f"{bet_code}|{match_id}|{bookmaker}|{selection}|{kickoff_date}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class AlertRecord:
    """One actionable value-bet alert.

    :ivar alert_id: deterministic hash of the natural key.
    :ivar bet_code: market code (plus params hash when params exist).
    :ivar match_id: :class:`~superbrain.core.models.Match.match_id`.
    :ivar bookmaker: bookmaker slug (``"sisal"``, ``"goldbet"``, …).
    :ivar selection: canonical selection label.
    :ivar edge: ``model_probability - 1/odds``.
    :ivar probability: model-estimated probability.
    :ivar odds: decimal odds at the bookmaker.
    :ivar kickoff: UTC kickoff datetime.
    :ivar home_team: canonical home team name.
    :ivar away_team: canonical away team name.
    :ivar league: league slug (``"serie_a"`` etc.) or ``None``.
    :ivar market: market code (without the params hash).
    :ivar params: frozen shallow copy of ``Outcome.params``.
    :ivar label: optional human-readable outcome label.
    :ivar captured_at: observation time of the quoted odds.
    """

    alert_id: str
    bet_code: str
    match_id: str
    bookmaker: str
    selection: str
    edge: float
    probability: float
    odds: float
    kickoff: datetime
    home_team: str
    away_team: str
    league: str | None
    market: str
    params: dict[str, object] = field(default_factory=dict)
    label: str | None = None
    captured_at: datetime | None = None

    @property
    def book_probability(self) -> float:
        """Implied probability quoted by the bookmaker."""
        return 1.0 / self.odds if self.odds > 0 else 0.0

    @property
    def match_label(self) -> str:
        return f"{self.home_team} vs {self.away_team}"

    @property
    def kickoff_date(self) -> date:
        return self.kickoff.date()

    @classmethod
    def from_value_bet(cls, vb: ValueBet) -> AlertRecord:
        """Project a :class:`~superbrain.engine.pipeline.ValueBet` into an alert record.

        :param vb: engine-produced value bet.
        :return: deterministic :class:`AlertRecord`.
        """
        fixture = vb.fixture
        outcome = vb.priced.outcome
        params = dict(outcome.params)
        market_value = outcome.market.value
        bet_code = bet_code_from_market(market_value, params)
        kickoff = _ensure_utc_datetime(fixture.match_date)
        alert_id = compute_alert_id(
            bet_code=bet_code,
            match_id=fixture.match_id,
            bookmaker=vb.bookmaker,
            selection=outcome.selection,
            kickoff=kickoff,
        )
        captured = vb.captured_at
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=UTC)
        return cls(
            alert_id=alert_id,
            bet_code=bet_code,
            match_id=fixture.match_id,
            bookmaker=vb.bookmaker,
            selection=outcome.selection,
            edge=float(vb.edge),
            probability=float(vb.priced.model_probability),
            odds=float(vb.decimal_odds),
            kickoff=kickoff,
            home_team=fixture.home_team,
            away_team=fixture.away_team,
            league=fixture.league.value
            if hasattr(fixture.league, "value")
            else str(fixture.league),
            market=market_value,
            params=params,
            label=outcome.label,
            captured_at=captured,
        )


@dataclass(frozen=True)
class ChannelResult:
    """Outcome of one channel's attempt to send one alert.

    :ivar alert_id: the alert this result belongs to.
    :ivar channel: channel name (``"telegram"``, ``"email"``).
    :ivar status: ``"sent"`` | ``"failed"`` | ``"skipped"`` | ``"partial"``.
    :ivar sent_at: UTC timestamp the attempt finished.
    :ivar error: human-readable error (empty string when ``status == "sent"``).
    """

    alert_id: str
    channel: str
    status: str
    sent_at: datetime
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {"sent", "partial"}


@dataclass(frozen=True)
class AlertOutcome:
    """Full per-alert outcome: the record plus every channel's result."""

    alert: AlertRecord
    results: tuple[ChannelResult, ...]

    @property
    def ok(self) -> bool:
        return any(r.ok for r in self.results)


def _ensure_utc_datetime(value: datetime | date) -> datetime:
    """Coerce a ``date`` or naive ``datetime`` into a UTC-aware ``datetime``."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime(value.year, value.month, value.day, tzinfo=UTC)
