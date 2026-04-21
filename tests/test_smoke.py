"""Smoke test: every top-level package imports and declares the expected shape."""

from __future__ import annotations

import importlib

import superbrain

SUBPACKAGES = (
    "superbrain",
    "superbrain.core",
    "superbrain.data",
    "superbrain.scrapers",
    "superbrain.scrapers.historical",
    "superbrain.scrapers.bookmakers",
    "superbrain.engine",
    "superbrain.engine.bets",
    "superbrain.ablation",
    "superbrain.analytics",
    "superbrain.backtest",
    "superbrain.api",
    "superbrain.api.routers",
    "superbrain.api.alerts",
)


def test_all_subpackages_import() -> None:
    """Every planned package must import cleanly from an empty shell."""
    for name in SUBPACKAGES:
        importlib.import_module(name)


def test_version_is_declared() -> None:
    assert superbrain.__version__
