"""CLI entry-point: ``python -m superbrain.alerts --run-once``.

Used by the GitHub Actions fallback cron and the Fly.io worker when
in-process APScheduler isn't running. The CLI is intentionally tiny:
one flag, no subcommands.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from superbrain.alerts.config import AlertSettings
from superbrain.alerts.scheduler import run_alert_sweep
from superbrain.data.connection import Lake

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser (exposed for tests)."""
    parser = argparse.ArgumentParser(
        prog="python -m superbrain.alerts",
        description="Run one alert sweep against the configured lake.",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Required: run a single sweep and exit.",
    )
    parser.add_argument(
        "--lake",
        type=Path,
        default=None,
        help="Override SUPERBRAIN_LAKE_PATH (defaults to env / .env value).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default INFO).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and run one alert sweep.

    :param argv: explicit argument vector (defaults to ``sys.argv[1:]``).
    :return: process exit code (``0`` on success, ``1`` on usage error,
        ``2`` on dispatch failure).
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s"
    )

    if not args.run_once:
        print("error: --run-once is required", file=sys.stderr)
        return 1

    settings = AlertSettings()
    lake_path = args.lake or settings.lake_path
    lake = Lake(root=Path(lake_path))
    lake.ensure_schema()

    try:
        report = asyncio.run(run_alert_sweep(lake, settings=settings))
    except Exception:
        logger.exception("alerts.cli run_alert_sweep failed")
        return 2

    print(json.dumps(report.summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
