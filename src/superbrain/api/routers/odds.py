"""Odds router: paged, filtered reads over the ``odds`` lake partition."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

import anyio
import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query, status

from superbrain.api.deps import get_lake, require_auth
from superbrain.api.schemas import OddsRow, Page
from superbrain.data.connection import Lake

router = APIRouter(prefix="/odds", tags=["odds"], dependencies=[Depends(require_auth)])

_MAX_LIMIT = 5000


@router.get("", response_model=Page[OddsRow])
async def list_odds(
    lake: Annotated[Lake, Depends(get_lake)],
    match_id: Annotated[str | None, Query()] = None,
    bookmaker: Annotated[str | None, Query()] = None,
    market: Annotated[str | None, Query()] = None,
    season: Annotated[str | None, Query()] = None,
    captured_from: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 200,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[OddsRow]:
    """Return a page of ``OddsSnapshot`` rows, newest first."""
    rows, next_cursor = await anyio.to_thread.run_sync(
        _list_odds_sync,
        lake,
        match_id,
        bookmaker,
        market,
        season,
        captured_from,
        limit,
        cursor,
    )
    return Page[OddsRow](items=rows, count=len(rows), next_cursor=next_cursor)


def _list_odds_sync(
    lake: Lake,
    match_id: str | None,
    bookmaker: str | None,
    market: str | None,
    season: str | None,
    captured_from: datetime | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[OddsRow], str | None]:
    frame = lake.read_odds(bookmaker=bookmaker, market=market, season=season, since=captured_from)
    if frame.is_empty():
        return [], None
    if match_id is not None:
        frame = frame.filter(pl.col("match_id") == match_id)
    if frame.is_empty():
        return [], None
    frame = frame.sort("captured_at", descending=True)

    offset = _decode_cursor(cursor)
    window = frame.slice(offset, limit)
    total = frame.height
    next_cursor: str | None = None
    if offset + limit < total:
        next_cursor = _encode_cursor(offset + limit)

    rows: list[OddsRow] = []
    for row in window.iter_rows(named=True):
        rows.append(_row_to_model(row))
    return rows, next_cursor


def _row_to_model(row: dict[str, Any]) -> OddsRow:
    params_json = row.get("market_params_json") or "{}"
    try:
        params: dict[str, Any] = json.loads(params_json)
    except json.JSONDecodeError:
        params = {}
    return OddsRow(
        bookmaker=row["bookmaker"],
        bookmaker_event_id=row["bookmaker_event_id"],
        match_id=row.get("match_id"),
        match_label=row["match_label"],
        match_date=row["match_date"].isoformat()
        if hasattr(row["match_date"], "isoformat")
        else str(row["match_date"]),
        season=row["season"],
        league=row.get("league"),
        home_team=row["home_team"],
        away_team=row["away_team"],
        market=row["market"],
        market_params=params,
        selection=row["selection"],
        payout=row["payout"],
        captured_at=row["captured_at"],
        source=row["source"],
        run_id=row["run_id"],
    )


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
