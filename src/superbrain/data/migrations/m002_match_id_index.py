"""Seed an empty ``match_index.parquet`` for cross-source matching.

The match index is a small, frequently-rewritten parquet that stores the
canonical ``(match_id, league, season, match_date, home_team, away_team)``
rows. It exists so that ``OddsSnapshot.match_id`` can be back-filled after
the fact without rereading the full match partitions.
"""

from __future__ import annotations

import polars as pl

from superbrain.data.paths import LakeLayout

VERSION = 2
NAME = "match_index_parquet"


def apply(layout: LakeLayout) -> None:
    """Materialize ``matches/match_index.parquet`` with the canonical columns.

    :param layout: resolved lake layout
    """
    target = layout.matches_root / "match_index.parquet"
    if target.exists():
        return
    empty = pl.DataFrame(
        schema={
            "match_id": pl.String,
            "league": pl.String,
            "season": pl.String,
            "match_date": pl.Date,
            "home_team": pl.String,
            "away_team": pl.String,
        }
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    empty.write_parquet(target)
