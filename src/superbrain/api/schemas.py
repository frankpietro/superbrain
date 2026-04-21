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
    """Row returned by ``GET /matches``.

    ``home_xg`` / ``away_xg`` piggy-back on the list response so the
    Matches SPA card can render the past-fixture summary (FT + xG)
    without issuing a second request per row.
    """

    match_id: str
    league: str
    season: str
    match_date: str
    home_team: str
    away_team: str
    home_goals: int | None
    away_goals: int | None
    home_xg: float | None = None
    away_xg: float | None = None


class TeamMatchStatsRow(BaseModel):
    """Team-side of ``GET /matches/{match_id}/stats``.

    Mirrors the ``team_match_stats`` lake schema. Every metric is
    optional because different historical sources fill different
    columns and upcoming fixtures have no stats at all.
    """

    team: str
    is_home: bool
    goals: int | None = None
    goals_conceded: int | None = None
    ht_goals: int | None = None
    ht_goals_conceded: int | None = None
    shots: int | None = None
    shots_on_target: int | None = None
    shots_off_target: int | None = None
    shots_in_box: int | None = None
    corners: int | None = None
    fouls: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None
    offsides: int | None = None
    possession_pct: float | None = None
    passes: int | None = None
    pass_accuracy_pct: float | None = None
    tackles: int | None = None
    interceptions: int | None = None
    aerials_won: int | None = None
    saves: int | None = None
    big_chances: int | None = None
    big_chances_missed: int | None = None
    xg: float | None = None
    xga: float | None = None
    ppda: float | None = None
    source: str | None = None


class MatchStats(BaseModel):
    """Shape returned by ``GET /matches/{match_id}/stats``."""

    match_id: str
    home: TeamMatchStatsRow | None
    away: TeamMatchStatsRow | None


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


class UnmappedMarket(BaseModel):
    """One entry in a scraper's top-unmapped-markets list."""

    name: str
    count: int


class ScraperHistoryEntry(BaseModel):
    """Compact per-run slice rendered as a sparkline on the scrapers page."""

    run_id: str
    started_at: datetime
    rows_written: int
    status: str


class ScrapersStatusBookmaker(BaseModel):
    """Per-bookmaker status block for ``GET /scrapers/status``."""

    bookmaker: str
    last_run: ScrapeRunRow | None
    healthy: bool
    runs_24h: int
    rows_written_24h: int
    errors_24h: int
    unmapped_markets_top: list[UnmappedMarket] = Field(default_factory=list)
    history: list[ScraperHistoryEntry] = Field(default_factory=list)


class ScrapersStatus(BaseModel):
    """Shape returned by ``GET /scrapers/status``.

    Wraps the per-bookmaker blocks in the ``items`` envelope used by every
    other list endpoint so the SPA can lean on a single response shape.
    """

    items: list[ScrapersStatusBookmaker]


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


class TrendsVariabilityRow(BaseModel):
    """One row of ``GET /trends/variability``.

    Each row is an aggregate over a ``group_by`` bucket (market / team / match).
    Volatility is reported as the mean coefficient of variation of the
    underlying selection-level payout series, in percent.
    """

    key: str
    label: str
    series_count: int
    observation_count: int
    avg_cv_pct: float
    max_cv_pct: float
    avg_range_pct: float
    avg_payout: float
    leagues: list[str] = Field(default_factory=list)


class TrendsVariabilityResponse(BaseModel):
    """Shape returned by ``GET /trends/variability``."""

    group_by: str
    since_hours: int
    min_points: int
    total_series: int
    items: list[TrendsVariabilityRow]


class TrendsTtkBucket(BaseModel):
    """One time-to-kickoff bucket in ``GET /trends/time-to-kickoff``."""

    hours_min: float
    hours_max: float
    n_transitions: int
    n_series: int
    mean_abs_delta_pct: float
    median_abs_delta_pct: float
    p90_abs_delta_pct: float
    prob_any_change: float


class TrendsTimeToKickoffResponse(BaseModel):
    """Shape returned by ``GET /trends/time-to-kickoff``."""

    bucket_hours: int
    total_transitions: int
    buckets: list[TrendsTtkBucket]
