"""APScheduler wiring and graceful lifecycle for the always-on worker.

This module keeps the scheduler as "boring code" that can be re-entered by
tests. Everything stateful — the ``Lake``, the ``AsyncIOScheduler``, the
structlog setup — is created inside :func:`start` (or injected) rather
than at import time.

Failure modes the runner is explicit about:

* A job that raises inside APScheduler is logged and skipped; the next
  tick still fires. The jobs themselves in :mod:`.jobs` already convert
  all exceptions into a ``failed`` :class:`ScrapeRun` row, so this is a
  defensive belt.
* ``SIGTERM`` / ``SIGINT`` trigger an orderly shutdown via an
  ``asyncio.Event`` the ``start()`` coroutine awaits on. Fly.io sends
  ``SIGTERM`` 10 seconds before it halts a machine; structlog output
  before shutdown lets us see what was in flight.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from superbrain.api.logging_config import configure_logging
from superbrain.data.connection import Lake
from superbrain.scheduler.config import SchedulerSettings
from superbrain.scheduler.jobs import (
    JOB_CALLABLES,
    JobName,
    backfill_historical,
    scrape_eurobet,
    scrape_goldbet,
    scrape_sisal,
)

log = structlog.get_logger(__name__)


def build_scheduler(
    lake: Lake,
    settings: SchedulerSettings,
    *,
    scheduler: AsyncIOScheduler | None = None,
    now: datetime | None = None,
) -> AsyncIOScheduler:
    """Create and register every job on an :class:`AsyncIOScheduler`.

    The caller owns the scheduler's start/stop lifecycle. Tests pass an
    already-constructed scheduler and a pinned ``now`` so trigger
    arithmetic is deterministic.

    :param lake: already-initialized lake; passed as the first arg to every
        job callable
    :param settings: :class:`SchedulerSettings` (cadence + timeouts)
    :param scheduler: optional pre-built :class:`AsyncIOScheduler`; a new
        one is created when ``None``
    :param now: optional pinned reference timestamp for stagger offsets;
        defaults to ``datetime.now(UTC)``
    :return: the scheduler, with all jobs added but not started
    """
    sch = scheduler or AsyncIOScheduler(
        timezone="UTC",
        job_defaults={
            "coalesce": True,
            "max_instances": max(1, settings.max_concurrent_jobs),
            "misfire_grace_time": 60,
        },
    )
    reference = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
    stagger = max(0, settings.bookmaker_stagger_minutes)
    interval = max(1, settings.bookmaker_interval_minutes)

    sch.add_job(
        func=_job_wrapper(scrape_sisal, lake, settings),
        trigger=IntervalTrigger(
            minutes=interval,
            start_date=reference + timedelta(minutes=0 * stagger),
        ),
        id=JobName.SISAL.value,
        name="scrape_sisal",
        replace_existing=True,
    )
    sch.add_job(
        func=_job_wrapper(scrape_goldbet, lake, settings),
        trigger=IntervalTrigger(
            minutes=interval,
            start_date=reference + timedelta(minutes=1 * stagger),
        ),
        id=JobName.GOLDBET.value,
        name="scrape_goldbet",
        replace_existing=True,
    )
    sch.add_job(
        func=_job_wrapper(scrape_eurobet, lake, settings),
        trigger=IntervalTrigger(
            minutes=interval,
            start_date=reference + timedelta(minutes=2 * stagger),
        ),
        id=JobName.EUROBET.value,
        name="scrape_eurobet",
        replace_existing=True,
    )
    sch.add_job(
        func=_historical_job_wrapper(lake, settings),
        trigger=CronTrigger.from_crontab(settings.historical_cron, timezone="UTC"),
        id=JobName.HISTORICAL.value,
        name="backfill_historical",
        replace_existing=True,
    )
    return sch


def _job_wrapper(
    coro: Callable[..., Awaitable[object]],
    lake: Lake,
    settings: SchedulerSettings,
) -> Callable[[], Awaitable[None]]:
    """Return a zero-arg async callable APScheduler can invoke."""

    async def _run() -> None:
        try:
            await coro(lake, timeout_seconds=settings.job_timeout_seconds)
        except Exception:  # pragma: no cover - jobs already swallow errors
            log.exception("scheduler.wrapper_caught", job=getattr(coro, "__name__", "job"))

    return _run


def _historical_job_wrapper(
    lake: Lake, settings: SchedulerSettings
) -> Callable[[], Awaitable[None]]:
    async def _run() -> None:
        try:
            await backfill_historical(
                lake,
                leagues=list(settings.historical_leagues),
                seasons=list(settings.historical_seasons),
                sources=list(settings.historical_sources),
                timeout_seconds=settings.job_timeout_seconds,
            )
        except Exception:  # pragma: no cover - defensive
            log.exception("scheduler.wrapper_caught", job=JobName.HISTORICAL.value)

    return _run


async def start(
    settings: SchedulerSettings | None = None,
    *,
    lake: Lake | None = None,
    install_signal_handlers: bool = True,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Boot the scheduler and block until asked to shut down.

    :param settings: :class:`SchedulerSettings`; a fresh one is loaded from
        the environment when ``None``
    :param lake: optional pre-built :class:`Lake`; constructed from
        ``settings.lake_path`` when ``None`` and
        :meth:`Lake.ensure_schema` is called before jobs fire
    :param install_signal_handlers: install ``SIGTERM`` / ``SIGINT``
        handlers that resolve the stop event (disabled in tests)
    :param stop_event: optional externally-owned :class:`asyncio.Event`;
        resolving it cleanly stops the scheduler
    """
    resolved_settings = settings or SchedulerSettings()
    configure_logging(resolved_settings.log_level)

    resolved_lake = lake or Lake(root=resolved_settings.lake_path)
    resolved_lake.ensure_schema()

    log.info(
        "scheduler.boot",
        lake=str(resolved_lake.root),
        bookmaker_interval_minutes=resolved_settings.bookmaker_interval_minutes,
        bookmaker_stagger_minutes=resolved_settings.bookmaker_stagger_minutes,
        historical_cron=resolved_settings.historical_cron,
        job_timeout_seconds=resolved_settings.job_timeout_seconds,
        max_concurrent_jobs=resolved_settings.max_concurrent_jobs,
    )

    sch = build_scheduler(resolved_lake, resolved_settings)
    sch.start()

    stop = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    if install_signal_handlers:
        for sig in (signal.SIGINT, signal.SIGTERM):
            # pragma: no cover - Windows / pytest loops may not support signals
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, stop.set)

    log.info("scheduler.ready", jobs=[j.id for j in sch.get_jobs()])

    try:
        await stop.wait()
    finally:
        log.info("scheduler.shutdown_start")
        sch.shutdown(wait=True)
        log.info("scheduler.shutdown_done")


async def run_once(
    lake: Lake,
    settings: SchedulerSettings,
    *,
    jobs: tuple[JobName, ...] | None = None,
) -> list[object]:
    """Fire every requested job exactly once and return their results.

    Used by the CLI's ``--run-once`` path (the GitHub Actions fallback).

    :param lake: lake the jobs write into
    :param settings: cadence-agnostic settings (timeouts still apply)
    :param jobs: subset of jobs to fire; defaults to every registered job
    :return: list of return values (``ScrapeRun`` instances) in the order
        the jobs were requested
    """
    resolved = jobs or tuple(JOB_CALLABLES.keys())
    results: list[object] = []
    for job_name in resolved:
        if job_name is JobName.HISTORICAL:
            results.append(
                await backfill_historical(
                    lake,
                    leagues=list(settings.historical_leagues),
                    seasons=list(settings.historical_seasons),
                    sources=list(settings.historical_sources),
                    timeout_seconds=settings.job_timeout_seconds,
                )
            )
        else:
            fn = JOB_CALLABLES[job_name]
            results.append(await fn(lake, timeout_seconds=settings.job_timeout_seconds))
    return results


__all__ = [
    "build_scheduler",
    "run_once",
    "start",
]
