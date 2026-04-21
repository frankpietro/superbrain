"""Pydantic models shared across the data lake, scrapers, and engine.

Every record that flows through ``Lake.ingest_*`` is validated against one
of these models first. Doing the validation at the pydantic layer rather
than at the polars/DuckDB layer gives us cheap forensics (which row, why it
failed, what it looked like) that survive into the ingest report.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from superbrain.core.markets import Market


class League(StrEnum):
    SERIE_A = "serie_a"
    PREMIER_LEAGUE = "premier_league"
    LA_LIGA = "la_liga"
    BUNDESLIGA = "bundesliga"
    LIGUE_1 = "ligue_1"


class Bookmaker(StrEnum):
    SISAL = "sisal"
    GOLDBET = "goldbet"
    EUROBET = "eurobet"


SEASON_REGEX = r"^\d{4}-\d{2}$"


class Season(BaseModel):
    """Season identifier in the ``YYYY-YY`` form (e.g. ``2024-25``)."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(pattern=SEASON_REGEX)

    @classmethod
    def from_legacy(cls, legacy: str) -> Season:
        """Build from the legacy ``"2425"`` packed form.

        :param legacy: 4-digit packed season code
        :return: normalized ``Season`` in ``YYYY-YY`` form
        """
        legacy = legacy.strip()
        if len(legacy) != 4 or not legacy.isdigit():
            raise ValueError(f"invalid legacy season code {legacy!r}")
        start_century = "20" if int(legacy[:2]) < 60 else "19"
        return cls(code=f"{start_century}{legacy[:2]}-{legacy[2:]}")

    def __str__(self) -> str:
        return self.code


def compute_match_id(home_team: str, away_team: str, match_date: date, league: League | str) -> str:
    """Deterministic match key shared across data sources.

    Canonical home/away team names plus the date plus the league are enough
    to uniquely identify a fixture within the top five European leagues.

    :param home_team: canonical home-team name
    :param away_team: canonical away-team name
    :param match_date: match date (UTC day)
    :param league: :class:`League` enum or its string value
    :return: 16-char hex match identifier
    """
    league_code = league.value if isinstance(league, League) else str(league)
    payload = f"{league_code}|{match_date.isoformat()}|{home_team}|{away_team}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class Match(BaseModel):
    """A scheduled or completed top-5-league fixture."""

    model_config = ConfigDict(frozen=True)

    match_id: str
    league: League
    season: str = Field(pattern=SEASON_REGEX)
    match_date: date
    home_team: str
    away_team: str
    home_goals: int | None = None
    away_goals: int | None = None
    source: str
    ingested_at: datetime

    @field_validator("home_team", "away_team")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _check_id(self) -> Match:
        expected = compute_match_id(self.home_team, self.away_team, self.match_date, self.league)
        if self.match_id != expected:
            raise ValueError(
                "match_id does not match hash(home,away,date,league): "
                f"got {self.match_id!r} expected {expected!r}"
            )
        return self


class TeamMatchStats(BaseModel):
    """Wide per-team per-match statistics.

    Every stat is optional because different sources expose different
    subsets. Null is legitimately distinct from zero (missing data vs. team
    took zero shots). The analytics engine handles nulls by excluding the
    match from a given stat's distribution, never by imputing.
    """

    model_config = ConfigDict(frozen=True)

    match_id: str
    team: str
    is_home: bool
    league: League
    season: str = Field(pattern=SEASON_REGEX)
    match_date: date

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

    source: str
    ingested_at: datetime


class TeamElo(BaseModel):
    """One team's ClubElo rating on a given date."""

    model_config = ConfigDict(frozen=True)

    team: str
    country: str
    snapshot_date: date
    elo: float
    rank: int | None = None
    source: str
    ingested_at: datetime


class IngestProvenance(BaseModel):
    """Provenance tag attached to every write into the lake.

    A scraper, a contributor upload, and the legacy-odds backfill all fill
    this in identically; it is the glue that makes ``scrape_runs`` a real
    audit log.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    run_id: str
    actor: str
    captured_at: datetime
    bookmaker: Bookmaker | None = None
    note: str | None = None

    @field_validator("captured_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v


class OddsSnapshot(BaseModel):
    """One bookmaker quote observed at one moment in time."""

    model_config = ConfigDict(frozen=True)

    bookmaker: Bookmaker
    bookmaker_event_id: str
    match_id: str | None
    match_label: str
    match_date: date
    season: str = Field(pattern=SEASON_REGEX)
    league: League | None
    home_team: str
    away_team: str

    market: Market
    market_params: dict[str, Any] = Field(default_factory=dict)
    selection: str
    payout: float = Field(gt=0.0)

    captured_at: datetime
    source: str
    run_id: str
    raw_json: str | None = None

    @field_validator("captured_at")
    @classmethod
    def _tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    @field_validator("market_params")
    @classmethod
    def _params_json_safe(cls, v: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(v, sort_keys=True, default=str)
        except (TypeError, ValueError) as e:
            raise ValueError(f"market_params must be JSON-serializable: {e}") from e
        return v

    def params_hash(self) -> str:
        """Stable hash of ``market_params`` for dedupe keys.

        :return: 12-char hex digest of the JSON-serialized params
        """
        payload = json.dumps(self.market_params, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    def natural_key(self) -> tuple[str, str, str, str, str, str]:
        """Tuple used for deterministic dedupe inside a single scrape run.

        :return: key tuple used by ingest to suppress duplicate rows
        """
        return (
            self.bookmaker.value,
            self.bookmaker_event_id,
            self.market.value,
            self.params_hash(),
            self.selection,
            self.captured_at.isoformat(),
        )


class IngestReport(BaseModel):
    """Result of an ``ingest_*`` call."""

    rows_received: int
    rows_written: int
    rows_skipped_duplicate: int = 0
    rows_rejected: int = 0
    rejected_reasons: dict[str, int] = Field(default_factory=dict)
    partitions_written: list[str] = Field(default_factory=list)

    def merge(self, other: IngestReport) -> IngestReport:
        """Combine two reports (useful when an ingest writes several tables).

        :param other: report produced by a secondary ingest step
        :return: merged report
        """
        reasons = dict(self.rejected_reasons)
        for k, v in other.rejected_reasons.items():
            reasons[k] = reasons.get(k, 0) + v
        return IngestReport(
            rows_received=self.rows_received + other.rows_received,
            rows_written=self.rows_written + other.rows_written,
            rows_skipped_duplicate=self.rows_skipped_duplicate + other.rows_skipped_duplicate,
            rows_rejected=self.rows_rejected + other.rows_rejected,
            rejected_reasons=reasons,
            partitions_written=[*self.partitions_written, *other.partitions_written],
        )


class ScrapeRun(BaseModel):
    """Audit row describing one scheduled scraper execution."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    bookmaker: Bookmaker | None
    scraper: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    rows_written: int = 0
    rows_rejected: int = 0
    error_message: str | None = None
    host: str | None = None
