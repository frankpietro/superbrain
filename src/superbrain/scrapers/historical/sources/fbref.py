"""soccerdata.FBref wrapper for the historical backfill.

FBref delivers advanced team-match stats (possession, passes, xG, tackles,
saves, aerials) that the other free sources do not. ``soccerdata.FBref``
tunnels through Cloudflare via ``undetected-chromedriver`` and works as of
soccerdata 1.9.0 despite the site's long-running scraping-protection push.

Cost model (observed in the phase-2 spike): a cold fetch costs ~3.5 minutes
per ``stat_type`` per league-season; the disk cache at
``~/soccerdata/data/FBref/`` returns in <5s thereafter. A full backfill
touching schedule/expected/passing/defense/misc/keeper for five leagues by
five seasons is therefore an unattended ~15h one-off, which is why this
source is opt-in in ``scripts/backfill_historical.py`` rather than a CI
default.

The module is intentionally dependency-light at import time: we only load
``soccerdata`` when :func:`fetch_league_season` is actually called, so users
who never request FBref enrichment (the CI default) never pay the import
cost and the ``historical`` extra remains optional.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Final, Protocol

import polars as pl

from superbrain.core.models import League

logger = logging.getLogger(__name__)

FBREF_LEAGUE_CODES: Final[dict[League, str]] = {
    League.SERIE_A: "ITA-Serie A",
    League.PREMIER_LEAGUE: "ENG-Premier League",
    League.LA_LIGA: "ESP-La Liga",
    League.BUNDESLIGA: "GER-Bundesliga",
    League.LIGUE_1: "FRA-Ligue 1",
}

DEFAULT_STAT_TYPES: Final[tuple[str, ...]] = (
    "schedule",
    "shooting",
    "keeper",
    "passing",
    "defense",
    "misc",
)

STAT_COLUMN_RENAMES: Final[dict[str, str]] = {
    "schedule_poss": "possession_pct",
    "shooting_standard_sh": "shots",
    "shooting_standard_sot": "shots_on_target",
    "shooting_expected_xg": "xg",
    "passing_total_cmp": "passes",
    "passing_total_cmp_pct": "pass_accuracy_pct",
    "defense_tackles_tkl": "tackles",
    "defense_int": "interceptions",
    "misc_aerial_duels_won": "aerials_won",
    "misc_performance_crdy": "yellow_cards",
    "misc_performance_crdr": "red_cards",
    "misc_performance_fls": "fouls",
    "misc_performance_off": "offsides",
    "keeper_performance_saves": "saves",
}


class FBrefAdapter(Protocol):
    """Protocol for the ``soccerdata.FBref`` read surface we use.

    Tests inject a fake conforming to this protocol so we never touch the
    network. Production wires :class:`SoccerdataFBref`.
    """

    def read_team_match_stats(self, stat_type: str):  # type: ignore[no-untyped-def]
        """Return a pandas DataFrame of team-match stats for the given table."""
        ...


class SoccerdataFBref:
    """Thin lazy wrapper around ``soccerdata.FBref``.

    :param league: league enum
    :param season: canonical season code
    """

    def __init__(self, league: League, season: str) -> None:
        import soccerdata as sd  # noqa: PLC0415  (soccerdata is an optional dep)

        self._fb = sd.FBref(
            leagues=FBREF_LEAGUE_CODES[league],
            seasons=_to_fbref_season(season),
        )

    def read_team_match_stats(self, stat_type: str):  # type: ignore[no-untyped-def]
        return self._fb.read_team_match_stats(stat_type=stat_type)


def fetch_league_season(
    league: League,
    season: str,
    *,
    stat_types: Iterable[str] = DEFAULT_STAT_TYPES,
    adapter: FBrefAdapter | None = None,
) -> pl.DataFrame:
    """Fetch and flatten FBref team-match stats for one league-season.

    :param league: league enum
    :param season: canonical season code
    :param stat_types: FBref ``stat_type`` tables to fetch. Defaults to the
        six tables the phase-1 engine cares about.
    :param adapter: optional adapter (used in tests to avoid network I/O);
        defaults to a real ``soccerdata.FBref`` instance
    :return: polars frame, one row per (team, match) with flattened and
        renamed columns. Empty frame when the source returns nothing.
    """
    if adapter is None:
        adapter = SoccerdataFBref(league, season)

    frames: list[pl.DataFrame] = []
    for stat_type in stat_types:
        logger.info("fbref: fetching stat_type=%s for %s %s", stat_type, league.value, season)
        pdf = adapter.read_team_match_stats(stat_type=stat_type)
        if pdf is None or len(pdf) == 0:
            continue
        pdf = pdf.reset_index()
        pdf.columns = [_flat_col_name(stat_type, c) for c in pdf.columns]
        frames.append(pl.from_pandas(_coerce_object_columns(pdf)))

    if not frames:
        return _empty_frame(league, season)

    base = frames[0]
    for other_raw in frames[1:]:
        join_cols = [
            c
            for c in ("league", "season", "team", "game", "date")
            if c in base.columns and c in other_raw.columns
        ]
        if not join_cols:
            continue
        drop_dup = [c for c in other_raw.columns if c in base.columns and c not in join_cols]
        other = other_raw.drop(drop_dup) if drop_dup else other_raw
        base = base.join(other, on=join_cols, how="left")

    base = _standardize_output(base, league=league, season=season)
    return base


def _standardize_output(df: pl.DataFrame, *, league: League, season: str) -> pl.DataFrame:
    renames = {old: new for old, new in STAT_COLUMN_RENAMES.items() if old in df.columns}
    if renames:
        df = df.rename(renames)

    if "date" in df.columns:
        df = df.with_columns(
            pl.col("date").cast(pl.String).str.strptime(pl.Date, strict=False).alias("match_date")
        )
    elif "game" in df.columns:
        df = df.with_columns(
            pl.col("game")
            .str.extract(r"^(\d{4}-\d{2}-\d{2})")
            .str.strptime(pl.Date, strict=False)
            .alias("match_date")
        )
    else:
        df = df.with_columns(pl.lit(None).cast(pl.Date).alias("match_date"))

    if "team" in df.columns:
        df = df.rename({"team": "team_raw"})
    if "opponent" in df.columns:
        df = df.rename({"opponent": "opponent_raw"})

    if "venue" in df.columns:
        df = df.with_columns((pl.col("venue").str.to_lowercase() == "home").alias("is_home"))
    else:
        df = df.with_columns(pl.lit(None).cast(pl.Boolean).alias("is_home"))

    df = df.with_columns(
        pl.lit("fbref").alias("source"),
        pl.lit(league.value).alias("league_slug"),
        pl.lit(season).alias("season_code"),
    )
    df = df.drop([c for c in ("league", "season") if c in df.columns])
    df = df.rename({"league_slug": "league", "season_code": "season"})
    return df


def _flat_col_name(stat_type: str, col: object) -> str:
    if isinstance(col, tuple):
        parts = [str(p).strip() for p in col if p is not None and str(p).strip()]
        name = "_".join(parts).lower().replace(" ", "_").replace("/", "_").replace("%", "pct")
    else:
        name = str(col).lower()
    if name in {"league", "season", "team", "game", "date", "venue", "opponent"}:
        return name
    return f"{stat_type}_{name}"


def _coerce_object_columns(pdf: object) -> object:
    """Coerce pandas ``object`` columns to ``string`` so polars can ingest them."""
    for col in pdf.columns:  # type: ignore[attr-defined]
        if pdf[col].dtype == object:  # type: ignore[index]
            pdf[col] = pdf[col].astype("string")  # type: ignore[index]
    return pdf


def _to_fbref_season(season: str) -> str:
    """Convert ``"2023-24"`` to FBref's ``"2023-2024"`` form.

    :param season: canonical season code
    :return: four-digit-start/four-digit-end season label
    """
    if len(season) != 7 or season[4] != "-":
        raise ValueError(f"expected YYYY-YY, got {season!r}")
    start = season[:4]
    end_short = season[5:7]
    end = (
        f"{start[:2]}{end_short}"
        if int(end_short) >= int(start[2:4])
        else f"{int(start[:2]) + 1}{end_short}"
    )
    return f"{start}-{end}"


def _empty_frame(league: League, season: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "team_raw": pl.Series([], dtype=pl.String),
            "opponent_raw": pl.Series([], dtype=pl.String),
            "is_home": pl.Series([], dtype=pl.Boolean),
            "match_date": pl.Series([], dtype=pl.Date),
            "source": pl.Series([], dtype=pl.String),
            "league": pl.Series([], dtype=pl.String),
            "season": pl.Series([], dtype=pl.String),
        }
    ).with_columns(
        pl.lit(league.value).alias("league"),
        pl.lit(season).alias("season"),
    )
