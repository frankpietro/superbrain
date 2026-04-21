"""Tests for :mod:`superbrain.scheduler.config`."""

from __future__ import annotations

from pathlib import Path

import pytest

from superbrain.scheduler.config import DEFAULT_LEAGUES, SchedulerSettings


def test_defaults_align_with_fly_toml(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(__import__("os").environ.keys()):
        if key.startswith("SUPERBRAIN_"):
            monkeypatch.delenv(key, raising=False)
    s = SchedulerSettings()
    assert s.bookmaker_interval_minutes == 15
    assert s.bookmaker_stagger_minutes == 5
    assert s.historical_cron == "0 4 * * mon-fri"
    assert s.job_timeout_seconds == 600
    assert s.max_concurrent_jobs == 2
    assert s.historical_leagues == DEFAULT_LEAGUES


def test_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SUPERBRAIN_LAKE_PATH", str(tmp_path / "lake"))
    monkeypatch.setenv("SUPERBRAIN_SCHEDULER_BOOKMAKER_INTERVAL_MINUTES", "20")
    monkeypatch.setenv("SUPERBRAIN_SCHEDULER_JOB_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("SUPERBRAIN_SCHEDULER_HISTORICAL_CRON", "30 5 * * *")
    s = SchedulerSettings()
    assert s.lake_path == tmp_path / "lake"
    assert s.bookmaker_interval_minutes == 20
    assert s.job_timeout_seconds == 120
    assert s.historical_cron == "30 5 * * *"


def test_invalid_cron_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERBRAIN_SCHEDULER_HISTORICAL_CRON", "   ")
    with pytest.raises(ValueError):
        SchedulerSettings()


def test_interval_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERBRAIN_SCHEDULER_BOOKMAKER_INTERVAL_MINUTES", "0")
    with pytest.raises(ValueError):
        SchedulerSettings()
