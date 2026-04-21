"""Command-line entry point for the always-on scheduler.

Usage::

    python -m superbrain.scheduler                 # boot the long-running loop
    python -m superbrain.scheduler --run-once      # fire every job once, exit
    python -m superbrain.scheduler --run-once --jobs bookmakers
    python -m superbrain.scheduler --run-once --jobs historical

``--run-once`` is what the GitHub Actions fallback workflow calls — it
fires the requested jobs synchronously and exits non-zero if any job
emitted ``status=failed``. Long-running Fly.io containers use the
zero-argument form.

The CLI is an internal tool (the phase-1 brief disallows a user-facing
CLI). It is shipped so the Fly container and the Actions runner have a
single deterministic entry point.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

import structlog

from superbrain.api.logging_config import configure_logging
from superbrain.data.connection import Lake
from superbrain.scheduler.config import SchedulerSettings
from superbrain.scheduler.jobs import BOOKMAKER_JOBS, JobName
from superbrain.scheduler.runner import run_once, start

log = structlog.get_logger(__name__)


_JOB_GROUPS: dict[str, tuple[JobName, ...]] = {
    "all": tuple(JobName),
    "bookmakers": BOOKMAKER_JOBS,
    "historical": (JobName.HISTORICAL,),
    "sisal": (JobName.SISAL,),
    "goldbet": (JobName.GOLDBET,),
    "eurobet": (JobName.EUROBET,),
}


def build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser used by :func:`main`.

    :return: configured :class:`argparse.ArgumentParser`
    """
    p = argparse.ArgumentParser(
        prog="python -m superbrain.scheduler",
        description="superbrain always-on scheduler (Phase 5)",
    )
    p.add_argument(
        "--run-once",
        action="store_true",
        help="Fire every requested job once, synchronously, then exit.",
    )
    p.add_argument(
        "--jobs",
        default="all",
        choices=sorted(_JOB_GROUPS.keys()),
        help="Subset of jobs to run with --run-once (default: all).",
    )
    p.add_argument(
        "--log-level",
        default=None,
        help="Override SUPERBRAIN_SCHEDULER_LOG_LEVEL for this invocation.",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    """Process entry point.

    :param argv: optional argument vector (defaults to ``sys.argv[1:]``)
    :return: process exit code
    """
    args = build_parser().parse_args(argv)
    settings = SchedulerSettings()
    if args.log_level:
        settings = settings.model_copy(update={"log_level": args.log_level})
    configure_logging(settings.log_level)

    if args.run_once:
        jobs = _JOB_GROUPS[args.jobs]
        return asyncio.run(_run_once(settings, jobs))

    asyncio.run(start(settings))
    return 0


async def _run_once(settings: SchedulerSettings, jobs: tuple[JobName, ...]) -> int:
    lake = Lake(root=settings.lake_path)
    lake.ensure_schema()
    log.info(
        "scheduler.cli.run_once",
        jobs=[j.value for j in jobs],
        lake=str(lake.root),
    )
    results = await run_once(lake, settings, jobs=jobs)
    failed = [
        getattr(r, "run_id", "?") for r in results if getattr(r, "status", "success") == "failed"
    ]
    if failed:
        log.error("scheduler.cli.run_once.some_failed", runs=failed)
        return 1
    log.info("scheduler.cli.run_once.ok", runs=len(results))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["build_parser", "main"]
