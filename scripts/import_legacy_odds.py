"""One-off script: import the legacy ``betting_odds.db`` into the lake.

Usage::

    uv run python scripts/import_legacy_odds.py \
        --sqlite /path/to/fbref24/refactored_src/data/betting_odds.db \
        --lake data/lake

The script is idempotent: re-running it will not duplicate rows because
``Lake.ingest_odds`` dedupes on ``natural_key``. A final ``IngestReport`` is
printed and also written to ``data/lake/scrape_runs/legacy_import-*.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog

from superbrain.core.models import IngestProvenance, ScrapeRun
from superbrain.data.connection import Lake
from superbrain.data.legacy_odds import legacy_rows_to_snapshots

LOG = structlog.get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--sqlite",
        required=True,
        type=Path,
        help="Path to the legacy betting_odds.db SQLite database",
    )
    p.add_argument(
        "--lake",
        required=True,
        type=Path,
        help="Lake root (will be created if missing)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the actual write; just report what would happen",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.sqlite.exists():
        print(f"error: sqlite path {args.sqlite} does not exist", file=sys.stderr)
        return 2

    run_id = f"legacy_import:{uuid.uuid4()}"
    started = datetime.now(tz=UTC)

    lake = Lake(args.lake)
    lake.ensure_schema()

    LOG.info("legacy_import.start", run_id=run_id, sqlite=str(args.sqlite))
    snapshots, rejected = legacy_rows_to_snapshots(str(args.sqlite), run_id=run_id)
    LOG.info(
        "legacy_import.parsed",
        snapshots=len(snapshots),
        rejected=sum(rejected.values()),
    )

    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "snapshots": len(snapshots),
                    "rejected": rejected,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    provenance = IngestProvenance(
        source="legacy_sqlite",
        run_id=run_id,
        actor="script:import_legacy_odds",
        captured_at=started,
        note=f"sqlite={args.sqlite}",
    )
    report = lake.ingest_odds(snapshots, provenance=provenance)
    finished = datetime.now(tz=UTC)

    lake.log_scrape_run(
        ScrapeRun(
            run_id=run_id,
            bookmaker=None,
            scraper="legacy_import",
            started_at=started,
            finished_at=finished,
            status="success",
            rows_written=report.rows_written,
            rows_rejected=sum(rejected.values()),
            host=None,
        )
    )

    summary = report.model_dump()
    summary["rejected_reasons_legacy_parse"] = rejected
    summary["run_id"] = run_id
    summary["duration_seconds"] = (finished - started).total_seconds()
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
