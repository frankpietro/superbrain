"""Job coroutines wired into APScheduler and the ``--run-once`` CLI.

Each job:

1. Opens (or reuses) a :class:`superbrain.data.connection.Lake`.
2. Invokes the per-bookmaker ``scrape()`` or the historical
   ``run_backfill()`` entry point.
3. Writes a scheduler-level :class:`ScrapeRun` audit row tagged with the
   ``scheduler.<job>`` scraper identifier so it stays distinct from the
   per-bookmaker audit row the scraper already writes.
4. Never raises: the scheduler cannot drop a loop because one scraper
   errored. Errors are captured into the audit row and propagated back as
   the return value for tests and for the ``--run-once`` CLI to surface.

``n_events`` / ``n_rows`` as mentioned in the phase-5 brief map to the
pydantic contract that actually exists on ``ScrapeRun``
(``rows_written`` / ``rows_rejected``). The raw per-league event counts
live inside the scraper's own audit row; the scheduler's row is the
outer "scheduler invocation happened, here is the result" trail.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from superbrain.core.models import Bookmaker, League, ScrapeRun
from superbrain.data.connection import Lake
from superbrain.scheduler.config import (
    DEFAULT_HISTORICAL_SEASONS,
    DEFAULT_HISTORICAL_SOURCES,
    DEFAULT_LEAGUES,
)
from superbrain.scrapers.bookmakers.eurobet import scraper as eurobet_scraper
from superbrain.scrapers.bookmakers.goldbet import scraper as goldbet_scraper
from superbrain.scrapers.bookmakers.sisal import scraper as sisal_scraper

log = structlog.get_logger(__name__)


def _load_backfill_module() -> Any:
    """Import ``scripts/backfill_historical.py`` lazily.

    The backfill orchestrator lives under ``scripts/`` (not the importable
    ``superbrain`` package) because it is the human-invoked CLI. The
    scheduler reuses its ``run_backfill`` coroutine by adding ``scripts/``
    to ``sys.path`` on first call.

    :return: the ``backfill_historical`` module
    """
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    if scripts_dir.is_dir() and str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import backfill_historical  # noqa: PLC0415

    return backfill_historical


class JobName(StrEnum):
    """Stable identifiers used by APScheduler and the CLI."""

    SISAL = "scrape_sisal"
    GOLDBET = "scrape_goldbet"
    EUROBET = "scrape_eurobet"
    HISTORICAL = "backfill_historical"


BOOKMAKER_JOBS: tuple[JobName, ...] = (
    JobName.SISAL,
    JobName.GOLDBET,
    JobName.EUROBET,
)


def _make_run_id(prefix: str) -> str:
    return f"sched-{prefix}-{uuid4().hex[:12]}"


def _truncate(msg: str, limit: int = 1024) -> str:
    return msg if len(msg) <= limit else msg[:limit]


def _log_run(
    lake: Lake,
    run: ScrapeRun,
) -> None:
    try:
        lake.log_scrape_run(run)
    except Exception as e:  # pragma: no cover - defensive; lake write errors are rare
        log.error("scheduler.log_scrape_run_failed", run_id=run.run_id, error=str(e))


async def _run_with_timeout(
    coro: Awaitable[Any],
    *,
    timeout_seconds: int | None,
) -> Any:
    if timeout_seconds is None or timeout_seconds <= 0:
        return await coro
    return await asyncio.wait_for(coro, timeout=timeout_seconds)


async def scrape_sisal(
    lake: Lake,
    *,
    timeout_seconds: int | None = None,
    scrape_fn: Callable[..., Awaitable[Any]] | None = None,
) -> ScrapeRun:
    """Scheduler job: run the Sisal prematch scrape end-to-end.

    :param lake: lake the scrape writes into
    :param timeout_seconds: optional soft timeout wrapped around the scrape
    :param scrape_fn: override for the underlying ``scrape`` coroutine
        (tests inject a stub); defaults to the real Sisal scraper
    :return: the scheduler-level :class:`ScrapeRun` that was logged
    """
    return await _run_bookmaker_job(
        lake=lake,
        job=JobName.SISAL,
        bookmaker=Bookmaker.SISAL,
        scrape_fn=scrape_fn or sisal_scraper.scrape,
        timeout_seconds=timeout_seconds,
    )


async def scrape_goldbet(
    lake: Lake,
    *,
    timeout_seconds: int | None = None,
    scrape_fn: Callable[..., Awaitable[Any]] | None = None,
) -> ScrapeRun:
    """Scheduler job: run the Goldbet prematch scrape end-to-end.

    :param lake: lake the scrape writes into
    :param timeout_seconds: optional soft timeout wrapped around the scrape
    :param scrape_fn: override for the underlying ``scrape`` coroutine
    :return: the scheduler-level :class:`ScrapeRun` that was logged
    """
    return await _run_bookmaker_job(
        lake=lake,
        job=JobName.GOLDBET,
        bookmaker=Bookmaker.GOLDBET,
        scrape_fn=scrape_fn or goldbet_scraper.scrape,
        timeout_seconds=timeout_seconds,
    )


async def scrape_eurobet(
    lake: Lake,
    *,
    timeout_seconds: int | None = None,
    scrape_fn: Callable[..., Awaitable[Any]] | None = None,
) -> ScrapeRun:
    """Scheduler job: run the Eurobet prematch scrape end-to-end.

    :param lake: lake the scrape writes into
    :param timeout_seconds: optional soft timeout wrapped around the scrape
    :param scrape_fn: override for the underlying ``scrape`` coroutine
    :return: the scheduler-level :class:`ScrapeRun` that was logged
    """
    return await _run_bookmaker_job(
        lake=lake,
        job=JobName.EUROBET,
        bookmaker=Bookmaker.EUROBET,
        scrape_fn=scrape_fn or eurobet_scraper.scrape,
        timeout_seconds=timeout_seconds,
    )


async def _run_bookmaker_job(
    *,
    lake: Lake,
    job: JobName,
    bookmaker: Bookmaker,
    scrape_fn: Callable[..., Awaitable[Any]],
    timeout_seconds: int | None,
) -> ScrapeRun:
    run_id = _make_run_id(bookmaker.value)
    started_at = datetime.now(UTC)
    status = "success"
    rows_written = 0
    rows_rejected = 0
    error_message: str | None = None

    log.info("scheduler.job_start", job=job.value, run_id=run_id)
    try:
        result = await _run_with_timeout(scrape_fn(lake), timeout_seconds=timeout_seconds)
        rows_written, rows_rejected, inner_status, inner_error = _summarize_scrape_result(result)
        if inner_error:
            error_message = inner_error
        if inner_status in {"failed", "partial"}:
            status = inner_status
    except TimeoutError:
        status = "failed"
        error_message = f"timeout after {timeout_seconds}s"
        log.error("scheduler.job_timeout", job=job.value, run_id=run_id, timeout=timeout_seconds)
    except Exception as e:
        status = "failed"
        error_message = _truncate(f"{type(e).__name__}: {e}")
        log.exception("scheduler.job_failed", job=job.value, run_id=run_id)

    finished_at = datetime.now(UTC)
    run = ScrapeRun(
        run_id=run_id,
        bookmaker=bookmaker,
        scraper=f"scheduler.{job.value}",
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        rows_written=rows_written,
        rows_rejected=rows_rejected,
        error_message=_truncate(error_message) if error_message else None,
        host=socket.gethostname(),
    )
    _log_run(lake, run)
    log.info(
        "scheduler.job_done",
        job=job.value,
        run_id=run_id,
        status=status,
        rows_written=rows_written,
        rows_rejected=rows_rejected,
        duration_s=(finished_at - started_at).total_seconds(),
    )
    return run


def _summarize_scrape_result(result: Any) -> tuple[int, int, str, str | None]:
    """Extract ``(rows_written, rows_rejected, status, error_message)``.

    Sisal and Eurobet return a result dataclass with rich fields; Goldbet
    returns an ``IngestReport`` directly. Normalise into the four values
    the scheduler's ``ScrapeRun`` needs.
    """
    rows_written = int(getattr(result, "rows_written", 0) or 0)
    rows_rejected = int(getattr(result, "rows_rejected", 0) or 0)
    status = str(getattr(result, "status", "success") or "success")

    errors = getattr(result, "errors", None)
    error_message: str | None = None
    if isinstance(errors, Sequence) and errors:
        error_message = "; ".join(str(e) for e in errors)

    if not hasattr(result, "rows_written") and hasattr(result, "rows_received"):
        rows_written = int(result.rows_written) if hasattr(result, "rows_written") else 0

    return rows_written, rows_rejected, status, error_message


async def backfill_historical(
    lake: Lake,
    *,
    leagues: Sequence[str] | None = None,
    seasons: Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
    timeout_seconds: int | None = None,
    backfill_fn: Callable[..., Awaitable[Any]] | None = None,
) -> ScrapeRun:
    """Scheduler job: pull the historical backfill for the requested slice.

    :param lake: lake the backfill writes into
    :param leagues: league slugs to backfill; defaults to the top-5
    :param seasons: season codes (``YYYY-YY``) to backfill
    :param sources: source tags to pull (``football_data``, ``understat``,
        ``fbref``, ``clubelo``)
    :param timeout_seconds: optional soft timeout wrapped around the job
    :param backfill_fn: override for the underlying ``run_backfill``
        coroutine (tests inject a stub)
    :return: the scheduler-level :class:`ScrapeRun` that was logged
    """
    run_id = _make_run_id("historical")
    started_at = datetime.now(UTC)
    status = "success"
    rows_written = 0
    rows_rejected = 0
    error_message: str | None = None

    resolved_leagues = tuple(leagues) if leagues else DEFAULT_LEAGUES
    resolved_seasons = tuple(seasons) if seasons else DEFAULT_HISTORICAL_SEASONS
    resolved_sources = tuple(sources) if sources else DEFAULT_HISTORICAL_SOURCES

    log.info(
        "scheduler.job_start",
        job=JobName.HISTORICAL.value,
        run_id=run_id,
        leagues=resolved_leagues,
        seasons=resolved_seasons,
        sources=resolved_sources,
    )

    try:
        fn = backfill_fn
        if fn is None:
            bf = _load_backfill_module()
            fn = bf.run_backfill

        league_enums = [League(slug) for slug in resolved_leagues]
        coro = fn(
            lake,
            leagues=league_enums,
            seasons=list(resolved_seasons),
            sources=list(resolved_sources),
        )
        report = await _run_with_timeout(coro, timeout_seconds=timeout_seconds)

        rows_written = (
            int(getattr(report, "total_matches_written", 0) or 0)
            + int(getattr(report, "total_stats_written", 0) or 0)
            + int(getattr(report, "total_elo_written", 0) or 0)
        )
        per_ls = getattr(report, "per_league_season", []) or []
        rows_rejected = sum(int(getattr(r, "rejected", 0) or 0) for r in per_ls)
        aggregated_errors: list[str] = []
        for r in per_ls:
            errs = getattr(r, "errors", None) or []
            aggregated_errors.extend(f"{r.league}/{r.season}:{e}" for e in errs)
        if aggregated_errors:
            error_message = "; ".join(aggregated_errors)
            status = "partial"
    except TimeoutError:
        status = "failed"
        error_message = f"timeout after {timeout_seconds}s"
        log.error(
            "scheduler.job_timeout",
            job=JobName.HISTORICAL.value,
            run_id=run_id,
            timeout=timeout_seconds,
        )
    except Exception as e:
        status = "failed"
        error_message = _truncate(f"{type(e).__name__}: {e}")
        log.exception("scheduler.job_failed", job=JobName.HISTORICAL.value, run_id=run_id)

    finished_at = datetime.now(UTC)
    run = ScrapeRun(
        run_id=run_id,
        bookmaker=None,
        scraper=f"scheduler.{JobName.HISTORICAL.value}",
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        rows_written=rows_written,
        rows_rejected=rows_rejected,
        error_message=_truncate(error_message) if error_message else None,
        host=socket.gethostname(),
    )
    _log_run(lake, run)
    log.info(
        "scheduler.job_done",
        job=JobName.HISTORICAL.value,
        run_id=run_id,
        status=status,
        rows_written=rows_written,
        duration_s=(finished_at - started_at).total_seconds(),
    )
    return run


JOB_CALLABLES: dict[JobName, Callable[..., Awaitable[ScrapeRun]]] = {
    JobName.SISAL: scrape_sisal,
    JobName.GOLDBET: scrape_goldbet,
    JobName.EUROBET: scrape_eurobet,
    JobName.HISTORICAL: backfill_historical,
}


__all__ = [
    "BOOKMAKER_JOBS",
    "JOB_CALLABLES",
    "JobName",
    "backfill_historical",
    "eurobet_scraper",
    "goldbet_scraper",
    "scrape_eurobet",
    "scrape_goldbet",
    "scrape_sisal",
    "sisal_scraper",
]
