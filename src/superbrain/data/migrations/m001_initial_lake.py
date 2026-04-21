"""Seed the lake directory skeleton."""

from __future__ import annotations

from superbrain.data.paths import LakeLayout

VERSION = 1
NAME = "initial_lake_skeleton"


def apply(layout: LakeLayout) -> None:
    """Create the five table roots so downstream code can partition beneath them.

    :param layout: resolved lake layout
    """
    layout.root.mkdir(parents=True, exist_ok=True)
    for root in layout.iter_table_roots():
        root.mkdir(parents=True, exist_ok=True)
