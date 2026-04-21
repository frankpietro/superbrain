"""Trigger-wiring tests for :mod:`superbrain.scheduler.runner`.

APScheduler triggers are pure functions of ``(now, fire_time)``. We
exercise them directly (without running the scheduler loop) and assert
that over a simulated 1-hour window each job fires the expected number of
times, and that the three bookmaker triggers are staggered by 5 minutes
so they never fire on the same minute.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from superbrain.core.models import ScrapeRun
from superbrain.data.connection import Lake
from superbrain.scheduler import jobs as scheduler_jobs
from superbrain.scheduler.config import SchedulerSettings
from superbrain.scheduler.jobs import JobName
from superbrain.scheduler.runner import build_scheduler, run_once, start

REFERENCE = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)


def _count_fires(trigger: Any, start_time: datetime, end: datetime) -> list[datetime]:
    fires: list[datetime] = []
    previous: datetime | None = None
    now = start_time
    while True:
        nxt = trigger.get_next_fire_time(previous, now)
        if nxt is None or nxt >= end:
            break
        fires.append(nxt)
        previous = nxt
        now = nxt
    return fires


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SchedulerSettings:
    for k in list(os.environ.keys()):
        if k.startswith("SUPERBRAIN_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SUPERBRAIN_LAKE_PATH", str(tmp_path / "lake"))
    return SchedulerSettings()


@pytest.fixture
def lake_at(tmp_path: Path) -> Lake:
    root = tmp_path / "lake-runner"
    root.mkdir()
    lk = Lake(root=root)
    lk.ensure_schema()
    return lk


def test_bookmaker_triggers_stagger_and_cadence(lake_at: Lake, settings: SchedulerSettings) -> None:
    sch = build_scheduler(lake_at, settings, now=REFERENCE)
    end = REFERENCE + timedelta(hours=1)

    fires_by_job: dict[str, list[datetime]] = {}
    for job_id in (JobName.SISAL, JobName.GOLDBET, JobName.EUROBET):
        job = sch.get_job(job_id.value)
        assert job is not None
        fires_by_job[job_id.value] = _count_fires(
            job.trigger, REFERENCE - timedelta(seconds=1), end
        )

    assert [len(v) for v in fires_by_job.values()] == [4, 4, 4]

    all_minutes = [
        dt.replace(second=0, microsecond=0) for fires in fires_by_job.values() for dt in fires
    ]
    assert len(all_minutes) == len(set(all_minutes))

    firsts = [fires_by_job[j.value][0] for j in (JobName.SISAL, JobName.GOLDBET, JobName.EUROBET)]
    offsets = [(f - REFERENCE).total_seconds() / 60 for f in firsts]
    assert offsets == [0.0, 5.0, 10.0]


def test_historical_trigger_fires_weekdays_only(lake_at: Lake, settings: SchedulerSettings) -> None:
    sch = build_scheduler(lake_at, settings, now=REFERENCE)
    job = sch.get_job(JobName.HISTORICAL.value)
    assert job is not None

    end = REFERENCE + timedelta(days=14)
    fires = _count_fires(job.trigger, REFERENCE, end)
    assert len(fires) == 10
    for f in fires:
        assert f.hour == 4 and f.minute == 0
        assert f.weekday() < 5


async def _fake_scrape(lake: Lake, **kwargs: Any) -> Any:
    return type(
        "R",
        (),
        {
            "rows_written": 0,
            "rows_received": 0,
            "rows_rejected": 0,
            "status": "success",
            "errors": [],
        },
    )()


async def test_run_once_fires_selected_jobs(
    lake_at: Lake, settings: SchedulerSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scheduler_jobs.sisal_scraper, "scrape", _fake_scrape)
    monkeypatch.setattr(scheduler_jobs.goldbet_scraper, "scrape", _fake_scrape)
    monkeypatch.setattr(scheduler_jobs.eurobet_scraper, "scrape", _fake_scrape)

    results = await run_once(
        lake_at,
        settings,
        jobs=(JobName.SISAL, JobName.GOLDBET, JobName.EUROBET),
    )
    assert len(results) == 3
    for r in results:
        assert isinstance(r, ScrapeRun)
        assert r.status == "success"


async def test_start_shuts_down_cleanly(lake_at: Lake, settings: SchedulerSettings) -> None:
    stop = asyncio.Event()

    async def _stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(
        start(
            settings,
            lake=lake_at,
            install_signal_handlers=False,
            stop_event=stop,
        ),
        _stop_soon(),
    )
