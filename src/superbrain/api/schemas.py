"""Response envelopes shared across every router.

Every list endpoint returns :class:`Page`; every error returns
:class:`ErrorResponse`. These shapes are part of the API contract and must
remain stable across patch versions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Page[T](BaseModel):
    """Envelope for a page of records."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[T] = Field(default_factory=list)
    count: int = 0
    next_cursor: str | None = None


class ErrorResponse(BaseModel):
    """Envelope for errors returned by the API."""

    detail: str


class HealthScrapeRun(BaseModel):
    """Most-recent scrape-run timestamp per bookmaker."""

    bookmaker: str
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_status: str | None


class HealthResponse(BaseModel):
    """Shape returned by ``GET /health``."""

    status: str
    git_sha: str | None
    lake_present: bool
    last_scrape_runs: dict[str, HealthScrapeRun | None]


class SelectionQuote(BaseModel):
    """One selection's latest payout for a (market, bookmaker) pair."""

    selection: str
    payout: float
    market_params: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime


class MatchOddsGroup(BaseModel):
    """Latest odds for a match grouped by ``(market, bookmaker)``."""

    market: str
    bookmaker: str
    selections: list[SelectionQuote]


class MatchDetail(BaseModel):
    """Single-match detail returned by ``GET /matches/{match_id}``."""

    match_id: str
    league: str
    season: str
    match_date: str
    home_team: str
    away_team: str
    home_goals: int | None
    away_goals: int | None
    odds: list[MatchOddsGroup]


class MatchRow(BaseModel):
    """Row returned by ``GET /matches``."""

    match_id: str
    league: str
    season: str
    match_date: str
    home_team: str
    away_team: str
    home_goals: int | None
    away_goals: int | None


class OddsRow(BaseModel):
    """Row returned by ``GET /odds``."""

    bookmaker: str
    bookmaker_event_id: str
    match_id: str | None
    match_label: str
    match_date: str
    season: str
    league: str | None
    home_team: str
    away_team: str
    market: str
    market_params: dict[str, Any]
    selection: str
    payout: float
    captured_at: datetime
    source: str
    run_id: str


class ScrapeRunRow(BaseModel):
    """Row returned by ``GET /scrapers/runs``."""

    run_id: str
    bookmaker: str | None
    scraper: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    rows_written: int
    rows_rejected: int
    error_message: str | None
    host: str | None


class ScrapersStatusBookmaker(BaseModel):
    """Per-bookmaker status block for ``GET /scrapers/status``."""

    bookmaker: str
    last_run: ScrapeRunRow | None
    runs_24h: int
    rows_written_24h: int
    errors_24h: int


class ScrapersStatus(BaseModel):
    """Shape returned by ``GET /scrapers/status``."""

    bookmakers: list[ScrapersStatusBookmaker]


class MarketInfo(BaseModel):
    """One entry of ``GET /bets/markets``."""

    code: str
    category: str
    human_name: str
    param_keys: list[str]
    selections: list[str]
    target_stat: str | None


class ValueBetStub(BaseModel):
    """Placeholder shape for the (not-yet-wired) value-bet endpoint."""

    match_id: str
    market: str
    selection: str
    edge: float
    bookmaker: str
    payout: float
