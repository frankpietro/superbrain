"""ClubElo fetcher via ``soccerdata.ClubElo``.

ClubElo publishes a public, cache-friendly daily Elo rating per club. Unlike
football-data/Understat/FBref, ClubElo is **not** a per-match source: it's
per-team-per-date, used as a feature rather than as a match-identity source.
The lake stores it under a dedicated ``team_elo`` table (added by migration
m003) so the engine can join on ``(team, date)`` later without conflating
match rows.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Final, Protocol

import polars as pl

from superbrain.core.models import League

logger = logging.getLogger(__name__)

LEAGUE_COUNTRY: Final[dict[League, str]] = {
    League.SERIE_A: "ITA",
    League.PREMIER_LEAGUE: "ENG",
    League.LA_LIGA: "ESP",
    League.BUNDESLIGA: "GER",
    League.LIGUE_1: "FRA",
}


class ClubEloAdapter(Protocol):
    """Protocol for the ``soccerdata.ClubElo`` read surface we use."""

    def read_by_date(self, date: str | date):  # type: ignore[no-untyped-def]
        """Return a pandas DataFrame of all clubs' Elo snapshots on a date."""
        ...


class SoccerdataClubElo:
    """Thin lazy wrapper around ``soccerdata.ClubElo``."""

    def __init__(self) -> None:
        import soccerdata as sd  # noqa: PLC0415  (soccerdata is an optional dep)

        self._ce = sd.ClubElo()

    def read_by_date(self, date: str | date):  # type: ignore[no-untyped-def]
        return self._ce.read_by_date(date=date)


def fetch_snapshot(
    snapshot_date: date,
    *,
    leagues: list[League] | None = None,
    adapter: ClubEloAdapter | None = None,
) -> pl.DataFrame:
    """Fetch a ClubElo snapshot filtered to the requested top-5 leagues.

    :param snapshot_date: date to snapshot (ClubElo ships daily)
    :param leagues: leagues to filter to (defaults to all five)
    :param adapter: optional adapter (for tests); defaults to real
        ``soccerdata.ClubElo``
    :return: polars frame, one row per (team, snapshot_date)
    """
    if adapter is None:
        adapter = SoccerdataClubElo()
    if leagues is None:
        leagues = list(LEAGUE_COUNTRY)

    countries = {LEAGUE_COUNTRY[lg] for lg in leagues}
    logger.info("clubelo: fetching snapshot %s for %s", snapshot_date, countries)
    pdf = adapter.read_by_date(date=snapshot_date)
    if pdf is None or len(pdf) == 0:
        return _empty_frame()

    pdf = pdf.reset_index()
    pdf.columns = [str(c).lower() for c in pdf.columns]
    df = pl.from_pandas(_coerce_object_columns(pdf))

    if "country" in df.columns:
        df = df.filter(pl.col("country").is_in(list(countries)))

    df = df.with_columns(
        pl.lit(snapshot_date).alias("snapshot_date"),
        pl.lit("clubelo").alias("source"),
    )
    return df


def _coerce_object_columns(pdf: object) -> object:
    """Coerce pandas ``object`` columns to ``string`` so polars can ingest them."""
    for col in pdf.columns:  # type: ignore[attr-defined]
        if pdf[col].dtype == object:  # type: ignore[index]
            pdf[col] = pdf[col].astype("string")  # type: ignore[index]
    return pdf


def _empty_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "club": pl.Series([], dtype=pl.String),
            "country": pl.Series([], dtype=pl.String),
            "elo": pl.Series([], dtype=pl.Float64),
            "snapshot_date": pl.Series([], dtype=pl.Date),
            "source": pl.Series([], dtype=pl.String),
        }
    )
