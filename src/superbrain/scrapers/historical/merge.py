"""Cross-source merge for historical matches.

Per the phase-2 spike ``docs/spike/historical-data-sources.md``:

* football-data.co.uk is the **authoritative row set**: every match present in
  the league-season is a row. Missing rows in Understat/FBref become
  left-joined nulls, never drop football-data rows.
* Canonicalize team names at merge time via
  :func:`superbrain.core.teams.canonicalize_team`. The raw names survive in
  ``home_team_raw`` / ``away_team_raw`` (or source-native columns) for
  forensic replay.
* Join keys are ``(match_date, canonical_home, canonical_away)``. Home/away
  is never rotated — every source stores the true home side in the "home"
  slot.
* Dedupe via ``compute_match_id`` (SHA-256 of
  ``league|date|canonical_home|canonical_away``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from superbrain.core.models import League, Match, TeamMatchStats, compute_match_id
from superbrain.core.teams import canonicalize_team

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MergedFrames:
    """Container returned by :func:`merge_sources`."""

    matches: list[Match]
    team_match_stats: list[TeamMatchStats]
    rejected: int
    rejected_reasons: dict[str, int]


def merge_sources(
    *,
    league: League,
    season: str,
    football_data: pl.DataFrame | None = None,
    understat: pl.DataFrame | None = None,
    fbref: pl.DataFrame | None = None,
    ingested_at: datetime | None = None,
) -> MergedFrames:
    """Build ``Match`` + ``TeamMatchStats`` rows from per-source frames.

    Any of the source arguments may be ``None`` or empty; in that case the
    corresponding columns come through as nulls. The return is validated
    against the pydantic contract, so every row that survives is safe to
    pass straight to ``Lake.ingest_matches`` / ``Lake.ingest_team_match_stats``.

    :param league: league enum for this league-season
    :param season: canonical season code
    :param football_data: frame from
        :func:`superbrain.scrapers.historical.sources.football_data.fetch_league_season`
    :param understat: frame from
        :func:`superbrain.scrapers.historical.sources.understat.fetch_league_season`
    :param fbref: frame from
        :func:`superbrain.scrapers.historical.sources.fbref.fetch_league_season`
    :param ingested_at: timestamp to stamp on every row; defaults to
        ``datetime.now(UTC)``
    :return: :class:`MergedFrames` ready for lake ingestion
    """
    ingested_at = ingested_at or datetime.now(tz=UTC)

    fd = (
        _canonicalize_pair(football_data, "football_data")
        if football_data is not None and football_data.height > 0
        else None
    )
    us = (
        _canonicalize_pair(understat, "understat")
        if understat is not None and understat.height > 0
        else None
    )
    fb = _canonicalize_fbref(fbref) if fbref is not None and fbref.height > 0 else None

    if fd is None and us is None and fb is None:
        return MergedFrames(matches=[], team_match_stats=[], rejected=0, rejected_reasons={})

    base_match = _build_base_matches(league, season, fd=fd, us=us, fb=fb)
    matches, rejected_matches, reasons = _emit_matches(
        base_match, league=league, season=season, ingested_at=ingested_at
    )
    stats, rejected_stats, stat_reasons = _emit_team_stats(
        base_match, fb=fb, league=league, season=season, ingested_at=ingested_at
    )

    combined_reasons: dict[str, int] = {}
    for r in (reasons, stat_reasons):
        for k, v in r.items():
            combined_reasons[k] = combined_reasons.get(k, 0) + v

    return MergedFrames(
        matches=matches,
        team_match_stats=stats,
        rejected=rejected_matches + rejected_stats,
        rejected_reasons=combined_reasons,
    )


def _non_empty(df: pl.DataFrame | None) -> bool:
    return df is not None and df.height > 0


def _canonicalize_pair(df: pl.DataFrame, source: str) -> pl.DataFrame:
    """Add ``canonical_home`` / ``canonical_away`` columns from raw names.

    :param df: source frame with ``home_team_raw`` / ``away_team_raw``
    :param source: source tag (used for logging only)
    :return: frame with two new columns; raw columns preserved
    """
    if "home_team_raw" not in df.columns or "away_team_raw" not in df.columns:
        logger.warning("%s: missing home/away raw columns, skipping", source)
        return df
    return df.with_columns(
        pl.col("home_team_raw")
        .map_elements(canonicalize_team, return_dtype=pl.String)
        .alias("canonical_home"),
        pl.col("away_team_raw")
        .map_elements(canonicalize_team, return_dtype=pl.String)
        .alias("canonical_away"),
    )


def _canonicalize_fbref(df: pl.DataFrame) -> pl.DataFrame:
    """Add ``canonical_team`` / ``canonical_opponent`` columns for FBref rows."""
    cols = df.columns
    expr: list[pl.Expr] = []
    if "team_raw" in cols:
        expr.append(
            pl.col("team_raw")
            .map_elements(canonicalize_team, return_dtype=pl.String)
            .alias("canonical_team")
        )
    if "opponent_raw" in cols:
        expr.append(
            pl.col("opponent_raw")
            .map_elements(canonicalize_team, return_dtype=pl.String)
            .alias("canonical_opponent")
        )
    return df.with_columns(expr) if expr else df


def _build_base_matches(
    league: League,
    season: str,
    *,
    fd: pl.DataFrame | None,
    us: pl.DataFrame | None,
    fb: pl.DataFrame | None,
) -> pl.DataFrame:
    """Full-outer-join the three match-level frames on the canonical keys."""
    join_cols = ("match_date", "canonical_home", "canonical_away")

    frames: list[pl.DataFrame] = []
    if fd is not None:
        frames.append(_prepare_fd_slice(fd))
    if us is not None:
        frames.append(_prepare_us_slice(us))
    if fb is not None:
        fb_match = _fbref_match_slice(fb)
        if _non_empty(fb_match):
            frames.append(fb_match)

    if not frames:
        return pl.DataFrame()

    base = frames[0]
    for other in frames[1:]:
        base = base.join(other, on=list(join_cols), how="full", coalesce=True)

    base = base.filter(
        pl.col("match_date").is_not_null()
        & pl.col("canonical_home").is_not_null()
        & pl.col("canonical_away").is_not_null()
    )
    base = base.with_columns(
        pl.lit(league.value).alias("league"),
        pl.lit(season).alias("season"),
    )
    return base


def _prepare_fd_slice(fd: pl.DataFrame) -> pl.DataFrame:
    renames = {
        "home_goals": "fd_home_goals",
        "away_goals": "fd_away_goals",
        "ht_home_goals": "fd_ht_home_goals",
        "ht_away_goals": "fd_ht_away_goals",
        "home_shots": "fd_home_shots",
        "away_shots": "fd_away_shots",
        "home_shots_on_target": "fd_home_sot",
        "away_shots_on_target": "fd_away_sot",
        "home_corners": "fd_home_corners",
        "away_corners": "fd_away_corners",
        "home_fouls": "fd_home_fouls",
        "away_fouls": "fd_away_fouls",
        "home_yellow_cards": "fd_home_yc",
        "away_yellow_cards": "fd_away_yc",
        "home_red_cards": "fd_home_rc",
        "away_red_cards": "fd_away_rc",
        "home_team_raw": "fd_home_team_raw",
        "away_team_raw": "fd_away_team_raw",
    }
    keep = ["match_date", "canonical_home", "canonical_away", *renames.keys()]
    keep = [c for c in keep if c in fd.columns]
    return fd.select(keep).rename({k: v for k, v in renames.items() if k in fd.columns})


def _prepare_us_slice(us: pl.DataFrame) -> pl.DataFrame:
    renames = {
        "home_goals": "us_home_goals",
        "away_goals": "us_away_goals",
        "home_xg": "us_home_xg",
        "away_xg": "us_away_xg",
        "forecast_home": "us_forecast_home",
        "forecast_draw": "us_forecast_draw",
        "forecast_away": "us_forecast_away",
        "understat_match_id": "us_match_id",
    }
    keep = ["match_date", "canonical_home", "canonical_away", *renames.keys()]
    keep = [c for c in keep if c in us.columns]
    return us.select(keep).rename({k: v for k, v in renames.items() if k in us.columns})


def _fbref_match_slice(fb: pl.DataFrame) -> pl.DataFrame:
    """Derive the match-level (date, home, away) slice from the FBref per-team frame.

    The input has one row per (team, match) with an ``is_home`` flag and
    ``canonical_team`` / ``canonical_opponent`` columns. Pivot to one row per
    match so it can join the match-level base.
    """
    cols = fb.columns
    if "is_home" not in cols or "canonical_team" not in cols or "canonical_opponent" not in cols:
        return pl.DataFrame()
    home = fb.filter(pl.col("is_home") == True).select(  # noqa: E712
        [
            pl.col("match_date"),
            pl.col("canonical_team").alias("canonical_home"),
            pl.col("canonical_opponent").alias("canonical_away"),
        ]
    )
    return home.unique().drop_nulls()


def _emit_matches(
    base: pl.DataFrame,
    *,
    league: League,
    season: str,
    ingested_at: datetime,
) -> tuple[list[Match], int, dict[str, int]]:
    if base.is_empty():
        return [], 0, {}
    out: list[Match] = []
    rejected = 0
    reasons: dict[str, int] = {}
    source = _combined_source_label(base.columns)
    for row in base.iter_rows(named=True):
        md = row["match_date"]
        home = row["canonical_home"]
        away = row["canonical_away"]
        home_goals = _pick_int(row, ("fd_home_goals", "us_home_goals"))
        away_goals = _pick_int(row, ("fd_away_goals", "us_away_goals"))
        try:
            m = Match(
                match_id=compute_match_id(home, away, md, league),
                league=league,
                season=season,
                match_date=md,
                home_team=home,
                away_team=away,
                home_goals=home_goals,
                away_goals=away_goals,
                source=source,
                ingested_at=ingested_at,
            )
        except Exception as exc:
            rejected += 1
            reasons[type(exc).__name__] = reasons.get(type(exc).__name__, 0) + 1
            logger.warning("match rejected: %s %s %s -> %s", md, home, away, exc)
            continue
        out.append(m)
    return out, rejected, reasons


def _emit_team_stats(
    base: pl.DataFrame,
    *,
    fb: pl.DataFrame | None,
    league: League,
    season: str,
    ingested_at: datetime,
) -> tuple[list[TeamMatchStats], int, dict[str, int]]:
    if base.is_empty():
        return [], 0, {}

    out: list[TeamMatchStats] = []
    rejected = 0
    reasons: dict[str, int] = {}
    source = _combined_source_label(base.columns)

    fb_lookup = _index_fbref(fb) if fb is not None else {}

    for row in base.iter_rows(named=True):
        md = row["match_date"]
        home = row["canonical_home"]
        away = row["canonical_away"]
        mid = compute_match_id(home, away, md, league)

        for is_home in (True, False):
            team = home if is_home else away
            opponent = away if is_home else home
            fd = _fd_stats_for(row, is_home=is_home)
            us = _us_stats_for(row, is_home=is_home)
            fb_row = fb_lookup.get((md, team, opponent))
            try:
                stats = TeamMatchStats(
                    match_id=mid,
                    team=team,
                    is_home=is_home,
                    league=league,
                    season=season,
                    match_date=md,
                    goals=fd.get("goals") if fd.get("goals") is not None else us.get("goals"),
                    goals_conceded=(
                        fd.get("goals_conceded")
                        if fd.get("goals_conceded") is not None
                        else us.get("goals_conceded")
                    ),
                    ht_goals=fd.get("ht_goals"),
                    ht_goals_conceded=fd.get("ht_goals_conceded"),
                    shots=fd.get("shots")
                    if fd.get("shots") is not None
                    else _fb_get_int(fb_row, "shots"),
                    shots_on_target=(
                        fd.get("shots_on_target")
                        if fd.get("shots_on_target") is not None
                        else _fb_get_int(fb_row, "shots_on_target")
                    ),
                    corners=fd.get("corners"),
                    fouls=(
                        fd.get("fouls")
                        if fd.get("fouls") is not None
                        else _fb_get_int(fb_row, "fouls")
                    ),
                    yellow_cards=(
                        fd.get("yellow_cards")
                        if fd.get("yellow_cards") is not None
                        else _fb_get_int(fb_row, "yellow_cards")
                    ),
                    red_cards=(
                        fd.get("red_cards")
                        if fd.get("red_cards") is not None
                        else _fb_get_int(fb_row, "red_cards")
                    ),
                    offsides=_fb_get_int(fb_row, "offsides"),
                    possession_pct=_fb_get_float(fb_row, "possession_pct"),
                    passes=_fb_get_int(fb_row, "passes"),
                    pass_accuracy_pct=_fb_get_float(fb_row, "pass_accuracy_pct"),
                    tackles=_fb_get_int(fb_row, "tackles"),
                    interceptions=_fb_get_int(fb_row, "interceptions"),
                    aerials_won=_fb_get_int(fb_row, "aerials_won"),
                    saves=_fb_get_int(fb_row, "saves"),
                    xg=us.get("xg") if us.get("xg") is not None else _fb_get_float(fb_row, "xg"),
                    xga=us.get("xga")
                    if us.get("xga") is not None
                    else _fb_get_float(fb_row, "xga"),
                    source=source,
                    ingested_at=ingested_at,
                )
            except Exception as exc:
                rejected += 1
                reasons[type(exc).__name__] = reasons.get(type(exc).__name__, 0) + 1
                logger.warning("stats rejected: %s %s -> %s", mid, team, exc)
                continue
            out.append(stats)
    return out, rejected, reasons


def _fd_stats_for(row: dict[str, object], *, is_home: bool) -> dict[str, int | None]:
    prefix = "fd_home_" if is_home else "fd_away_"
    opp_prefix = "fd_away_" if is_home else "fd_home_"
    return {
        "goals": _int_from(row.get(f"{prefix}goals")),
        "goals_conceded": _int_from(row.get(f"{opp_prefix}goals")),
        "ht_goals": _int_from(
            row.get("fd_ht_home_goals") if is_home else row.get("fd_ht_away_goals")
        ),
        "ht_goals_conceded": _int_from(
            row.get("fd_ht_away_goals") if is_home else row.get("fd_ht_home_goals")
        ),
        "shots": _int_from(row.get(f"{prefix}shots")),
        "shots_on_target": _int_from(row.get(f"{prefix}sot")),
        "corners": _int_from(row.get(f"{prefix}corners")),
        "fouls": _int_from(row.get(f"{prefix}fouls")),
        "yellow_cards": _int_from(row.get(f"{prefix}yc")),
        "red_cards": _int_from(row.get(f"{prefix}rc")),
    }


def _us_stats_for(row: dict[str, object], *, is_home: bool) -> dict[str, float | int | None]:
    side = "home" if is_home else "away"
    other = "away" if is_home else "home"
    return {
        "goals": _int_from(row.get(f"us_{side}_goals")),
        "goals_conceded": _int_from(row.get(f"us_{other}_goals")),
        "xg": _float_from(row.get(f"us_{side}_xg")),
        "xga": _float_from(row.get(f"us_{other}_xg")),
    }


def _index_fbref(fb: pl.DataFrame) -> dict[tuple[object, str, str], dict[str, object]]:
    cols = fb.columns
    needed = {"match_date", "canonical_team", "canonical_opponent"}
    if not needed.issubset(cols):
        return {}
    out: dict[tuple[object, str, str], dict[str, object]] = {}
    for row in fb.iter_rows(named=True):
        key = (row["match_date"], row["canonical_team"], row["canonical_opponent"])
        out[key] = row
    return out


def _fb_get_int(row: dict[str, object] | None, key: str) -> int | None:
    if row is None:
        return None
    return _int_from(row.get(key))


def _fb_get_float(row: dict[str, object] | None, key: str) -> float | None:
    if row is None:
        return None
    return _float_from(row.get(key))


def _pick_int(row: dict[str, object], keys: tuple[str, ...]) -> int | None:
    for k in keys:
        v = row.get(k)
        iv = _int_from(v)
        if iv is not None:
            return iv
    return None


def _int_from(v: object) -> int | None:
    if v is None:
        return None
    try:
        return int(v)  # type: ignore[call-overload, no-any-return]
    except (TypeError, ValueError):
        return None


def _float_from(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _combined_source_label(columns: list[str]) -> str:
    tags: list[str] = []
    if any(c.startswith("fd_") for c in columns):
        tags.append("football_data")
    if any(c.startswith("us_") for c in columns):
        tags.append("understat")
    if any(c in {"canonical_team", "canonical_opponent"} for c in columns):
        tags.append("fbref")
    return "+".join(tags) if tags else "historical"
