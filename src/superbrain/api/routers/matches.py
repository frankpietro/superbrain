"""Matches router: list and single-match detail with latest odds."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Any

import anyio
import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query, status

from superbrain.api.deps import get_lake, require_auth
from superbrain.api.schemas import (
    MatchDetail,
    MatchOddsGroup,
    MatchRow,
    Page,
    SelectionQuote,
)
from superbrain.data.connection import Lake

router = APIRouter(prefix="/matches", tags=["matches"], dependencies=[Depends(require_auth)])

_MAX_LIMIT = 500


@router.get("", response_model=Page[MatchRow])
async def list_matches(
    lake: Annotated[Lake, Depends(get_lake)],
    league: Annotated[str | None, Query()] = None,
    season: Annotated[str | None, Query()] = None,
    kickoff_from: Annotated[date | None, Query()] = None,
    kickoff_to: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[MatchRow]:
    """List matches in the lake, ordered by ``match_date`` descending."""
    rows, next_cursor = await anyio.to_thread.run_sync(
        _list_matches_sync,
        lake,
        league,
        season,
        kickoff_from,
        kickoff_to,
        limit,
        cursor,
    )
    return Page[MatchRow](items=rows, count=len(rows), next_cursor=next_cursor)


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


def _list_matches_sync(
    lake: Lake,
    league: str | None,
    season: str | None,
    kickoff_from: date | None,
    kickoff_to: date | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[MatchRow], str | None]:
    frame = lake.read_matches(league=league, season=season)
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

    rows: list[MatchRow] = []
    for row in window.iter_rows(named=True):
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
            )
        )
    return rows, next_cursor


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
