"""Add the ``team_elo`` table to the lake skeleton."""

from __future__ import annotations

from superbrain.data.paths import LakeLayout

VERSION = 3
NAME = "team_elo_root"


def apply(layout: LakeLayout) -> None:
    """Create the ``team_elo`` table root.

    :param layout: resolved lake layout
    """
    layout.team_elo_root.mkdir(parents=True, exist_ok=True)
