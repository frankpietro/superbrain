"""Live smoke test for the scheduler — gated on ``SUPERBRAIN_LIVE_TESTS=1``.

This fires every registered job once against the real lake under
``/tmp/sb-scheduler-smoke``. It is skipped in CI and in the default
``pytest -q`` run — the same contract used by the per-bookmaker live
tests.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from superbrain.data.connection import Lake
from superbrain.scheduler.config import SchedulerSettings
from superbrain.scheduler.jobs import JobName
from superbrain.scheduler.runner import run_once

pytestmark = pytest.mark.skipif(
    os.environ.get("SUPERBRAIN_LIVE_TESTS") != "1",
    reason="live scheduler smoke is opt-in; set SUPERBRAIN_LIVE_TESTS=1",
)


@pytest.mark.slow
@pytest.mark.integration
async def test_run_once_against_live_lake() -> None:
    root = Path("/tmp/sb-scheduler-smoke")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    lake = Lake(root=root / "lake")
    lake.ensure_schema()

    settings = SchedulerSettings(
        lake_path=root / "lake",
        bookmaker_interval_minutes=15,
        historical_seasons=("2024-25",),
    )
    results = await run_once(
        lake,
        settings,
        jobs=(JobName.SISAL, JobName.GOLDBET, JobName.EUROBET, JobName.HISTORICAL),
    )
    assert len(results) == 4
    # Every run produced an audit row regardless of status.
    assert (root / "lake" / "scrape_runs").exists()
