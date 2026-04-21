"""Trends router: odds-movement analytics over the lake's ``odds`` table.

Two endpoints, both read-only:

* ``GET /trends/variability?group_by=...`` answers
  *"how much do odds vary per market / per team / per match?"* by grouping
  selection-level time series into buckets and averaging each series's
  coefficient of variation (stddev / mean, in percent).
* ``GET /trends/time-to-kickoff`` answers
  *"how certain can we be that odds will change, given how far we are
  from kickoff?"* by pairing consecutive captures of every series, bucketing
  by their midpoint's distance to ``match_date``, and reporting summary
  statistics on the absolute percent change.

Both endpoints run on the same ``(bookmaker, bookmaker_event_id, market,
market_params_hash, selection)`` series definition — one selection's
payout through time is one series.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Annotated

import anyio
import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query, status

from superbrain.api.deps import get_lake
from superbrain.api.schemas import (
    TrendsTimeToKickoffResponse,
    TrendsTtkBucket,
    TrendsVariabilityResponse,
    TrendsVariabilityRow,
)
from superbrain.core.markets import MARKET_METADATA, Market
from superbrain.data.connection import Lake

router = APIRouter(prefix="/trends", tags=["trends"])

_GROUP_BY_CHOICES = {"market", "team", "match"}
_DEFAULT_SINCE_HOURS = 24 * 7
_DEFAULT_MIN_POINTS = 3
_DEFAULT_BUCKET_HOURS = 6
_MAX_ITEMS = 500
_SERIES_KEYS = (
    "bookmaker",
    "bookmaker_event_id",
    "market",
    "market_params_hash",
    "selection",
)


@router.get("/variability", response_model=TrendsVariabilityResponse)
async def variability(
    lake: Annotated[Lake, Depends(get_lake)],
    group_by: Annotated[str, Query(description="one of market|team|match")] = "market",
    league: Annotated[str | None, Query()] = None,
    bookmaker: Annotated[str | None, Query()] = None,
    since_hours: Annotated[int, Query(ge=1, le=24 * 365)] = _DEFAULT_SINCE_HOURS,
    min_points: Annotated[int, Query(ge=2, le=100)] = _DEFAULT_MIN_POINTS,
    limit: Annotated[int, Query(ge=1, le=_MAX_ITEMS)] = 50,
) -> TrendsVariabilityResponse:
    """Aggregate per-selection volatility into market / team / match buckets."""
    if group_by not in _GROUP_BY_CHOICES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"group_by must be one of {sorted(_GROUP_BY_CHOICES)}",
        )
    return await anyio.to_thread.run_sync(
        _variability_sync,
        lake,
        group_by,
        league,
        bookmaker,
        since_hours,
        min_points,
        limit,
    )


@router.get("/time-to-kickoff", response_model=TrendsTimeToKickoffResponse)
async def time_to_kickoff(
    lake: Annotated[Lake, Depends(get_lake)],
    bucket_hours: Annotated[int, Query(ge=1, le=48)] = _DEFAULT_BUCKET_HOURS,
    league: Annotated[str | None, Query()] = None,
    bookmaker: Annotated[str | None, Query()] = None,
    market: Annotated[str | None, Query()] = None,
    since_hours: Annotated[int, Query(ge=1, le=24 * 365)] = _DEFAULT_SINCE_HOURS,
    min_points: Annotated[int, Query(ge=2, le=100)] = _DEFAULT_MIN_POINTS,
) -> TrendsTimeToKickoffResponse:
    """Bucket consecutive odds changes by their midpoint's distance to kickoff."""
    return await anyio.to_thread.run_sync(
        _ttk_sync,
        lake,
        bucket_hours,
        league,
        bookmaker,
        market,
        since_hours,
        min_points,
    )


def _load_odds(
    lake: Lake,
    *,
    bookmaker: str | None,
    market: str | None,
    league: str | None,
    since_hours: int,
) -> pl.DataFrame:
    since = datetime.now(tz=UTC) - timedelta(hours=since_hours)
    frame = lake.read_odds(bookmaker=bookmaker, market=market, since=since)
    if frame.is_empty():
        return frame
    if league is not None:
        frame = frame.filter(pl.col("league") == league)
    return frame


def _variability_sync(
    lake: Lake,
    group_by: str,
    league: str | None,
    bookmaker: str | None,
    since_hours: int,
    min_points: int,
    limit: int,
) -> TrendsVariabilityResponse:
    frame = _load_odds(
        lake, bookmaker=bookmaker, market=None, league=league, since_hours=since_hours
    )
    empty = TrendsVariabilityResponse(
        group_by=group_by,
        since_hours=since_hours,
        min_points=min_points,
        total_series=0,
        items=[],
    )
    if frame.is_empty():
        return empty

    series = (
        frame.group_by(list(_SERIES_KEYS))
        .agg(
            pl.len().alias("n_points"),
            pl.col("payout").mean().alias("mean_payout"),
            pl.col("payout").std(ddof=0).alias("std_payout"),
            pl.col("payout").min().alias("min_payout"),
            pl.col("payout").max().alias("max_payout"),
            pl.col("match_id").first().alias("match_id"),
            pl.col("match_label").first().alias("match_label"),
            pl.col("home_team").first().alias("home_team"),
            pl.col("away_team").first().alias("away_team"),
            pl.col("league").first().alias("league"),
        )
        .filter(pl.col("n_points") >= min_points)
        .filter(pl.col("mean_payout") > 0)
    )
    if series.is_empty():
        return empty

    series = series.with_columns(
        (pl.col("std_payout") / pl.col("mean_payout") * 100.0).alias("cv_pct"),
        ((pl.col("max_payout") - pl.col("min_payout")) / pl.col("mean_payout") * 100.0).alias(
            "range_pct"
        ),
    )

    if group_by == "market":
        grouped = series.group_by("market").agg(
            pl.len().alias("series_count"),
            pl.col("n_points").sum().alias("observation_count"),
            pl.col("cv_pct").mean().alias("avg_cv_pct"),
            pl.col("cv_pct").max().alias("max_cv_pct"),
            pl.col("range_pct").mean().alias("avg_range_pct"),
            pl.col("mean_payout").mean().alias("avg_payout"),
            pl.col("league").unique().drop_nulls().alias("leagues"),
        )
        rows = [
            TrendsVariabilityRow(
                key=str(r["market"]),
                label=_market_label(str(r["market"])),
                series_count=int(r["series_count"]),
                observation_count=int(r["observation_count"]),
                avg_cv_pct=_finite(r["avg_cv_pct"]),
                max_cv_pct=_finite(r["max_cv_pct"]),
                avg_range_pct=_finite(r["avg_range_pct"]),
                avg_payout=_finite(r["avg_payout"]),
                leagues=sorted(r["leagues"] or []),
            )
            for r in grouped.iter_rows(named=True)
        ]
    elif group_by == "match":
        series_m = series.with_columns(
            pl.coalesce(pl.col("match_id"), pl.col("match_label")).alias("match_key"),
        )
        grouped = series_m.group_by("match_key").agg(
            pl.len().alias("series_count"),
            pl.col("n_points").sum().alias("observation_count"),
            pl.col("cv_pct").mean().alias("avg_cv_pct"),
            pl.col("cv_pct").max().alias("max_cv_pct"),
            pl.col("range_pct").mean().alias("avg_range_pct"),
            pl.col("mean_payout").mean().alias("avg_payout"),
            pl.col("match_label").first().alias("match_label"),
            pl.col("league").unique().drop_nulls().alias("leagues"),
        )
        rows = [
            TrendsVariabilityRow(
                key=str(r["match_key"]),
                label=str(r["match_label"] or r["match_key"]),
                series_count=int(r["series_count"]),
                observation_count=int(r["observation_count"]),
                avg_cv_pct=_finite(r["avg_cv_pct"]),
                max_cv_pct=_finite(r["max_cv_pct"]),
                avg_range_pct=_finite(r["avg_range_pct"]),
                avg_payout=_finite(r["avg_payout"]),
                leagues=sorted(r["leagues"] or []),
            )
            for r in grouped.iter_rows(named=True)
        ]
    else:  # team
        home = series.rename({"home_team": "team"}).select(
            ["team", "n_points", "cv_pct", "range_pct", "mean_payout", "league"]
        )
        away = series.rename({"away_team": "team"}).select(
            ["team", "n_points", "cv_pct", "range_pct", "mean_payout", "league"]
        )
        unioned = pl.concat([home, away], how="vertical_relaxed").drop_nulls("team")
        grouped = unioned.group_by("team").agg(
            pl.len().alias("series_count"),
            pl.col("n_points").sum().alias("observation_count"),
            pl.col("cv_pct").mean().alias("avg_cv_pct"),
            pl.col("cv_pct").max().alias("max_cv_pct"),
            pl.col("range_pct").mean().alias("avg_range_pct"),
            pl.col("mean_payout").mean().alias("avg_payout"),
            pl.col("league").unique().drop_nulls().alias("leagues"),
        )
        rows = [
            TrendsVariabilityRow(
                key=str(r["team"]),
                label=str(r["team"]),
                series_count=int(r["series_count"]),
                observation_count=int(r["observation_count"]),
                avg_cv_pct=_finite(r["avg_cv_pct"]),
                max_cv_pct=_finite(r["max_cv_pct"]),
                avg_range_pct=_finite(r["avg_range_pct"]),
                avg_payout=_finite(r["avg_payout"]),
                leagues=sorted(r["leagues"] or []),
            )
            for r in grouped.iter_rows(named=True)
        ]

    rows.sort(key=lambda r: (-r.avg_cv_pct, r.label))
    total_series = series.height
    return TrendsVariabilityResponse(
        group_by=group_by,
        since_hours=since_hours,
        min_points=min_points,
        total_series=total_series,
        items=rows[:limit],
    )


def _ttk_sync(
    lake: Lake,
    bucket_hours: int,
    league: str | None,
    bookmaker: str | None,
    market: str | None,
    since_hours: int,
    min_points: int,
) -> TrendsTimeToKickoffResponse:
    frame = _load_odds(
        lake, bookmaker=bookmaker, market=market, league=league, since_hours=since_hours
    )
    empty = TrendsTimeToKickoffResponse(bucket_hours=bucket_hours, total_transitions=0, buckets=[])
    if frame.is_empty():
        return empty

    # Sort each series by captured_at and compute consecutive-pair transitions.
    frame = frame.sort([*_SERIES_KEYS, "captured_at"])
    frame = frame.with_columns(
        pl.col("payout").shift(1).over(list(_SERIES_KEYS)).alias("prev_payout"),
        pl.col("captured_at").shift(1).over(list(_SERIES_KEYS)).alias("prev_captured_at"),
        pl.col("payout").count().over(list(_SERIES_KEYS)).alias("series_points"),
    )
    transitions = frame.filter(
        pl.col("prev_payout").is_not_null()
        & (pl.col("series_points") >= min_points)
        & (pl.col("prev_payout") > 0)
    )
    if transitions.is_empty():
        return empty

    # Kickoff proxy: match_date at 00:00:00 UTC (no kickoff_at in the odds schema).
    transitions = transitions.with_columns(
        pl.col("match_date").cast(pl.Datetime(time_unit="us", time_zone="UTC")).alias("kickoff"),
    )
    transitions = transitions.with_columns(
        ((pl.col("captured_at") - pl.col("prev_captured_at")).dt.total_seconds() / 2.0).alias(
            "mid_offset_s"
        ),
    )
    transitions = transitions.with_columns(
        (
            (
                pl.col("kickoff")
                - (pl.col("prev_captured_at") + pl.duration(seconds=pl.col("mid_offset_s")))
            ).dt.total_seconds()
            / 3600.0
        ).alias("hours_to_kickoff"),
        ((pl.col("payout") - pl.col("prev_payout")) / pl.col("prev_payout") * 100.0)
        .abs()
        .alias("abs_delta_pct"),
    )
    # Only keep pre-kickoff transitions (post-match odds are irrelevant here).
    transitions = transitions.filter(pl.col("hours_to_kickoff") >= 0)
    if transitions.is_empty():
        return empty

    transitions = transitions.with_columns(
        ((pl.col("hours_to_kickoff") / bucket_hours).floor().cast(pl.Int64) * bucket_hours).alias(
            "hours_min"
        ),
    )

    grouped = (
        transitions.group_by("hours_min")
        .agg(
            pl.len().alias("n_transitions"),
            pl.struct(list(_SERIES_KEYS)).n_unique().alias("n_series"),
            pl.col("abs_delta_pct").mean().alias("mean_abs_delta_pct"),
            pl.col("abs_delta_pct").median().alias("median_abs_delta_pct"),
            pl.col("abs_delta_pct")
            .quantile(0.9, interpolation="linear")
            .alias("p90_abs_delta_pct"),
            (pl.col("abs_delta_pct") > 0).mean().alias("prob_any_change"),
        )
        .sort("hours_min")
    )

    buckets = [
        TrendsTtkBucket(
            hours_min=float(r["hours_min"]),
            hours_max=float(r["hours_min"]) + float(bucket_hours),
            n_transitions=int(r["n_transitions"]),
            n_series=int(r["n_series"]),
            mean_abs_delta_pct=_finite(r["mean_abs_delta_pct"]),
            median_abs_delta_pct=_finite(r["median_abs_delta_pct"]),
            p90_abs_delta_pct=_finite(r["p90_abs_delta_pct"]),
            prob_any_change=_finite(r["prob_any_change"]),
        )
        for r in grouped.iter_rows(named=True)
    ]
    total_transitions = int(transitions.height)
    return TrendsTimeToKickoffResponse(
        bucket_hours=bucket_hours,
        total_transitions=total_transitions,
        buckets=buckets,
    )


def _market_label(code: str) -> str:
    try:
        meta = MARKET_METADATA[Market(code)]
    except (KeyError, ValueError):
        return code
    return meta.human_name


def _finite(value: object) -> float:
    if value is None:
        return 0.0
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(out) or math.isinf(out):
        return 0.0
    return out
