"""Env-driven settings for the always-on scheduler.

Every knob the scheduler exposes lives here. Defaults are tuned for the
Fly.io Hobby free-tier machine described in
``docs/deployment/scheduler.md``: every 15 minutes per bookmaker
(staggered 5 minutes apart so the three scrapers never fire at once),
daily historical backfill at 04:00 UTC Mon-Fri, per-job timeout 10 min,
max two overlapping jobs (one bookmaker + the tail of another,
never three live HTTP workloads at once).

The lake path defaults to ``./data/lake`` for local dev and is pinned to
``/data/lake`` by ``fly.toml`` so the persistent volume is authoritative
inside the Fly machine.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# APScheduler's ``CronTrigger.from_crontab`` uses APScheduler-native
# day-of-week indexing (0=Mon..6=Sun), not POSIX cron (0=Sun..6=Sat).
# Using named weekdays (``mon-fri``) avoids the silent off-by-one the two
# conventions would otherwise produce. See the Phase 5 knowledge-log
# entry in ``docs/knowledge.md`` for the full gotcha write-up.
DEFAULT_HISTORICAL_CRON = "0 4 * * mon-fri"
DEFAULT_LEAGUES = ("serie_a", "premier_league", "la_liga", "bundesliga", "ligue_1")
DEFAULT_HISTORICAL_SOURCES = ("football_data", "understat")
DEFAULT_HISTORICAL_SEASONS = ("2024-25", "2025-26")


class SchedulerSettings(BaseSettings):
    """Immutable configuration for the scheduler process.

    :param lake_path: filesystem path to the Parquet lake the jobs write into
    :param bookmaker_interval_minutes: cadence for each bookmaker job
    :param bookmaker_stagger_minutes: minute offset between the three
        bookmaker jobs so they never fire simultaneously
    :param historical_cron: crontab expression for the historical backfill
    :param historical_leagues: leagues the backfill should process
    :param historical_seasons: seasons the backfill should process
    :param historical_sources: source tags the backfill should pull
    :param job_timeout_seconds: soft timeout wrapped around each job run
    :param max_concurrent_jobs: APScheduler executor parallelism cap
    :param log_level: structlog / stdlib logging level
    """

    model_config = SettingsConfigDict(
        env_prefix="SUPERBRAIN_SCHEDULER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    lake_path: Path = Field(default=Path("./data/lake"), alias="SUPERBRAIN_LAKE_PATH")

    bookmaker_interval_minutes: int = Field(default=15, ge=1, le=720)
    bookmaker_stagger_minutes: int = Field(default=5, ge=0, le=60)

    historical_cron: str = Field(default=DEFAULT_HISTORICAL_CRON)
    historical_leagues: tuple[str, ...] = Field(default=DEFAULT_LEAGUES)
    historical_seasons: tuple[str, ...] = Field(default=DEFAULT_HISTORICAL_SEASONS)
    historical_sources: tuple[str, ...] = Field(default=DEFAULT_HISTORICAL_SOURCES)

    job_timeout_seconds: int = Field(default=600, ge=30, le=6 * 3600)
    max_concurrent_jobs: int = Field(default=2, ge=1, le=8)

    log_level: str = Field(default="INFO")

    @field_validator("historical_cron")
    @classmethod
    def _non_empty_cron(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("historical_cron must be a non-empty crontab expression")
        return stripped

    @field_validator("historical_leagues", "historical_seasons", "historical_sources")
    @classmethod
    def _non_empty_tuple(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        clean = tuple(s.strip() for s in v if s.strip())
        if not clean:
            raise ValueError("tuple setting must contain at least one non-empty entry")
        return clean


__all__ = [
    "DEFAULT_HISTORICAL_CRON",
    "DEFAULT_HISTORICAL_SEASONS",
    "DEFAULT_HISTORICAL_SOURCES",
    "DEFAULT_LEAGUES",
    "SchedulerSettings",
]
