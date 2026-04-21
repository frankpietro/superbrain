"""Matches router: list and single-match detail with latest odds."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Any

import anyio
import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query, status

from superbrain.api.deps import get_lake
from superbrain.api.schemas import (
    MatchDetail,
    MatchOddsGroup,
    MatchRow,
    MatchStats,
    Page,
    SelectionQuote,
    TeamMatchStatsRow,
)
from superbrain.data.connection import Lake

router = APIRouter(prefix="/matches", tags=["matches"])

_MAX_LIMIT = 500


@router.get("", response_model=Page[MatchRow])
async def list_matches(
    lake: Annotated[Lake, Depends(get_lake)],
    league: Annotated[str | None, Query()] = None,
    leagues: Annotated[list[str] | None, Query()] = None,
    season: Annotated[str | None, Query()] = None,
    kickoff_from: Annotated[date | None, Query()] = None,
    kickoff_to: Annotated[date | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[MatchRow]:
    """List matches in the lake, ordered by ``match_date`` descending.

    ``leagues`` (repeated) is honored in addition to the legacy ``league``
    singular param; ``date_from`` / ``date_to`` are accepted as aliases for
    ``kickoff_from`` / ``kickoff_to`` so the SPA filter bar stays in one
    vocabulary. When both forms are sent the newer plural/``date_*`` names
    win to keep client intent explicit.
    """
    effective_leagues = _resolve_leagues(league, leagues)
    effective_from = date_from if date_from is not None else kickoff_from
    effective_to = date_to if date_to is not None else kickoff_to
    rows, next_cursor = await anyio.to_thread.run_sync(
        _list_matches_sync,
        lake,
        effective_leagues,
        season,
        effective_from,
        effective_to,
        limit,
        cursor,
    )
    return Page[MatchRow](items=rows, count=len(rows), next_cursor=next_cursor)


def _resolve_leagues(league: str | None, leagues: list[str] | None) -> list[str] | None:
    """Return the effective league filter list or ``None`` for 'all'.

    Plural ``leagues`` wins over singular ``league`` when both are sent.
    """
    if leagues:
        cleaned = [lg for lg in leagues if lg]
        return cleaned or None
    if league:
        return [league]
    return None


@router.get("/{match_id}", response_model=MatchDetail)
async def get_match(
    match_id: str,
    lake: Annotated[Lake, Depends(get_lake)],
) -> MatchDetail:
    """Return a single match joined with its latest odds per (market, bookmaker)."""
    detail = await anyio.to_thread.run_sync(_match_detail_sync, lake, match_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="match not found")
    return detail


@router.get("/{match_id}/stats", response_model=MatchStats)
async def get_match_stats(
    match_id: str,
    lake: Annotated[Lake, Depends(get_lake)],
) -> MatchStats:
    """Return the home + away ``team_match_stats`` rows for one fixture.

    Empty ``home`` / ``away`` (``null``) means the lake has no stats for
    that side yet — expected for upcoming fixtures and for seasons the
    historical backfill hasn't processed. 404 is only raised when the
    fixture itself is unknown.
    """
    stats = await anyio.to_thread.run_sync(_match_stats_sync, lake, match_id)
    if stats is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="match not found")
    return stats


def _list_matches_sync(
    lake: Lake,
    leagues: list[str] | None,
    season: str | None,
    kickoff_from: date | None,
    kickoff_to: date | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[MatchRow], str | None]:
    if leagues:
        frames = [lake.read_matches(league=lg, season=season) for lg in leagues]
        frames = [f for f in frames if not f.is_empty()]
        frame = pl.concat(frames) if frames else lake.read_matches().head(0)
    else:
        frame = lake.read_matches(season=season)
    if frame.is_empty():
        return [], None
    if kickoff_from is not None:
        frame = frame.filter(pl.col("match_date") >= kickoff_from)
    if kickoff_to is not None:
        frame = frame.filter(pl.col("match_date") <= kickoff_to)
    frame = frame.sort(["match_date", "match_id"], descending=[True, False])

    offset = _decode_cursor(cursor)
    window = frame.slice(offset, limit)
    total = frame.height
    next_cursor: str | None = None
    if offset + limit < total:
        next_cursor = _encode_cursor(offset + limit)

    xg_lookup = _xg_lookup(lake, window["match_id"].to_list())

    rows: list[MatchRow] = []
    for row in window.iter_rows(named=True):
        home_xg, away_xg = xg_lookup.get(row["match_id"], (None, None))
        rows.append(
            MatchRow(
                match_id=row["match_id"],
                league=row["league"],
                season=row["season"],
                match_date=_iso_date(row["match_date"]),
                home_team=row["home_team"],
                away_team=row["away_team"],
                home_goals=row.get("home_goals"),
                away_goals=row.get("away_goals"),
                home_xg=home_xg,
                away_xg=away_xg,
            )
        )
    return rows, next_cursor


def _xg_lookup(lake: Lake, match_ids: list[str]) -> dict[str, tuple[float | None, float | None]]:
    """Return ``{match_id: (home_xg, away_xg)}`` for the given fixtures.

    Reads the entire ``team_match_stats`` table once and filters down in
    memory — one round-trip per list request, cheaper than joining on
    the lake for the typical ≤100-row page. Rows with no matching stats
    are simply absent from the result dict (caller fills None).
    """
    if not match_ids:
        return {}
    stats = lake.read_team_match_stats()
    if stats.is_empty():
        return {}
    slice_ = stats.filter(pl.col("match_id").is_in(match_ids)).select(["match_id", "is_home", "xg"])
    if slice_.is_empty():
        return {}
    out: dict[str, tuple[float | None, float | None]] = {}
    for row in slice_.iter_rows(named=True):
        mid = row["match_id"]
        home_xg, away_xg = out.get(mid, (None, None))
        xg = row.get("xg")
        if row.get("is_home"):
            home_xg = xg
        else:
            away_xg = xg
        out[mid] = (home_xg, away_xg)
    return out


def _match_stats_sync(lake: Lake, match_id: str) -> MatchStats | None:
    matches = lake.read_matches()
    if matches.is_empty():
        return None
    if matches.filter(pl.col("match_id") == match_id).is_empty():
        return None

    stats = lake.read_team_match_stats(match_id=match_id)
    home_row: TeamMatchStatsRow | None = None
    away_row: TeamMatchStatsRow | None = None
    for row in stats.iter_rows(named=True):
        team_row = TeamMatchStatsRow(
            team=row["team"],
            is_home=bool(row["is_home"]),
            goals=row.get("goals"),
            goals_conceded=row.get("goals_conceded"),
            ht_goals=row.get("ht_goals"),
            ht_goals_conceded=row.get("ht_goals_conceded"),
            shots=row.get("shots"),
            shots_on_target=row.get("shots_on_target"),
            shots_off_target=row.get("shots_off_target"),
            shots_in_box=row.get("shots_in_box"),
            corners=row.get("corners"),
            fouls=row.get("fouls"),
            yellow_cards=row.get("yellow_cards"),
            red_cards=row.get("red_cards"),
            offsides=row.get("offsides"),
            possession_pct=row.get("possession_pct"),
            passes=row.get("passes"),
            pass_accuracy_pct=row.get("pass_accuracy_pct"),
            tackles=row.get("tackles"),
            interceptions=row.get("interceptions"),
            aerials_won=row.get("aerials_won"),
            saves=row.get("saves"),
            big_chances=row.get("big_chances"),
            big_chances_missed=row.get("big_chances_missed"),
            xg=row.get("xg"),
            xga=row.get("xga"),
            ppda=row.get("ppda"),
            source=row.get("source"),
        )
        if team_row.is_home:
            home_row = team_row
        else:
            away_row = team_row
    return MatchStats(match_id=match_id, home=home_row, away=away_row)


def _match_detail_sync(lake: Lake, match_id: str) -> MatchDetail | None:
    matches = lake.read_matches()
    if matches.is_empty():
        return None
    row_frame = matches.filter(pl.col("match_id") == match_id)
    if row_frame.is_empty():
        return None
    row = row_frame.row(0, named=True)

    odds = lake.read_odds()
    groups: list[MatchOddsGroup] = []
    if not odds.is_empty():
        match_odds = odds.filter(pl.col("match_id") == match_id)
        if match_odds.is_empty():
            match_odds = odds.filter(
                (pl.col("home_team") == row["home_team"])
                & (pl.col("away_team") == row["away_team"])
                & (pl.col("match_date") == row["match_date"])
            )
        if not match_odds.is_empty():
            groups = _group_latest_odds(match_odds)

    return MatchDetail(
        match_id=row["match_id"],
        league=row["league"],
        season=row["season"],
        match_date=_iso_date(row["match_date"]),
        home_team=row["home_team"],
        away_team=row["away_team"],
        home_goals=row.get("home_goals"),
        away_goals=row.get("away_goals"),
        odds=groups,
    )


def _group_latest_odds(match_odds: pl.DataFrame) -> list[MatchOddsGroup]:
    latest = (
        match_odds.sort("captured_at", descending=True)
        .group_by(["market", "bookmaker", "selection", "market_params_hash"], maintain_order=True)
        .head(1)
    )
    groups: dict[tuple[str, str], list[SelectionQuote]] = {}
    for row in latest.iter_rows(named=True):
        key = (row["market"], row["bookmaker"])
        params_json = row.get("market_params_json") or "{}"
        try:
            params: dict[str, Any] = json.loads(params_json)
        except json.JSONDecodeError:
            params = {}
        quote = SelectionQuote(
            selection=row["selection"],
            payout=row["payout"],
            market_params=params,
            captured_at=_ensure_dt(row["captured_at"]),
        )
        groups.setdefault(key, []).append(quote)
    return [
        MatchOddsGroup(market=market, bookmaker=bookmaker, selections=quotes)
        for (market, bookmaker), quotes in sorted(groups.items())
    ]


def _iso_date(value: date | str) -> str:
    if isinstance(value, str):
        return value
    return value.isoformat()


def _ensure_dt(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid cursor"
        ) from exc
    if offset < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid cursor")
    return offset


def _encode_cursor(offset: int) -> str:
    return str(offset)
