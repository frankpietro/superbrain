"""APScheduler-based always-on worker for superbrain.

Phase 5 deliverable. The scheduler drives the three bookmaker scrapers on
a short fixed cadence and the historical backfill on a daily cron. It is
designed to run in-process inside a Fly.io machine for free always-on
coverage, with a GitHub Actions ``--run-once`` path used as a scheduled
fallback in case the Fly machine is suspended.

Public surface kept intentionally small:

* :func:`superbrain.scheduler.runner.start` — start the async scheduler.
* :class:`superbrain.scheduler.config.SchedulerSettings` — env-driven
  configuration.
* :mod:`superbrain.scheduler.jobs` — the four job coroutines the CLI and
  the runner share.
"""

from __future__ import annotations

from superbrain.scheduler.config import SchedulerSettings
from superbrain.scheduler.jobs import (
    JobName,
    backfill_historical,
    scrape_eurobet,
    scrape_goldbet,
    scrape_sisal,
)
from superbrain.scheduler.runner import build_scheduler, start

__all__ = [
    "JobName",
    "SchedulerSettings",
    "backfill_historical",
    "build_scheduler",
    "scrape_eurobet",
    "scrape_goldbet",
    "scrape_sisal",
    "start",
]
