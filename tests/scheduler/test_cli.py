"""Tests for :mod:`superbrain.scheduler.cli`."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from superbrain.core.models import ScrapeRun
from superbrain.scheduler import cli
from superbrain.scheduler.jobs import JobName


def test_parser_run_once_flags() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["--run-once", "--jobs", "bookmakers"])
    assert args.run_once is True
    assert args.jobs == "bookmakers"


def test_parser_rejects_unknown_group() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--run-once", "--jobs", "poker"])


def _fake_run(status: str = "success") -> ScrapeRun:
    return ScrapeRun(
        run_id=f"fake-{status}",
        bookmaker=None,
        scraper="test",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status=status,
    )


def test_main_run_once_exits_zero_on_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SUPERBRAIN_LAKE_PATH", str(tmp_path / "lake"))

    async def fake_run_once(
        lake: Any, settings: Any, *, jobs: tuple[JobName, ...] | None = None
    ) -> list[Any]:
        assert jobs == tuple(JobName)  # default "all"
        return [_fake_run("success"), _fake_run("partial")]

    monkeypatch.setattr(cli, "run_once", fake_run_once)
    code = cli.main(["--run-once"])
    assert code == 0


def test_main_run_once_fails_when_job_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SUPERBRAIN_LAKE_PATH", str(tmp_path / "lake"))

    async def fake_run_once(
        lake: Any, settings: Any, *, jobs: tuple[JobName, ...] | None = None
    ) -> list[Any]:
        return [_fake_run("success"), _fake_run("failed")]

    monkeypatch.setattr(cli, "run_once", fake_run_once)
    code = cli.main(["--run-once", "--jobs", "historical"])
    assert code == 1


def test_main_run_once_bookmakers_group(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SUPERBRAIN_LAKE_PATH", str(tmp_path / "lake"))

    seen: dict[str, object] = {}

    async def fake_run_once(
        lake: Any, settings: Any, *, jobs: tuple[JobName, ...] | None = None
    ) -> list[Any]:
        seen["jobs"] = jobs
        return [_fake_run("success") for _ in (jobs or ())]

    monkeypatch.setattr(cli, "run_once", fake_run_once)
    assert cli.main(["--run-once", "--jobs", "bookmakers"]) == 0
    assert seen["jobs"] == (JobName.SISAL, JobName.GOLDBET, JobName.EUROBET)
