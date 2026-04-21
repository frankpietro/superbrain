"""Map the legacy ``betting_odds.db`` schema onto :class:`OddsSnapshot`.

Every legacy table has a different column set but a common core:
``date``, ``season``, ``match``, ``bookmaker``, ``payout`` plus market-specific
extras. The mapping here is the source of truth for the one-off backfill
script (``scripts/import_legacy_odds.py``) and for tests that want a small
synthetic legacy DB to exercise the ingest pipeline.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from datetime import datetime, time, timezone
from typing import Any

from superbrain.core.markets import Market
from superbrain.core.models import (
    Bookmaker,
    OddsSnapshot,
    Season,
)
from superbrain.core.teams import canonicalize_match_string, split_match_string


LEGACY_TABLE_TO_MARKET: dict[str, Market] = {
    "odds_corner_1x2": Market.CORNER_1X2,
    "odds_corner_combo": Market.CORNER_COMBO,
    "odds_corner_first_to": Market.CORNER_FIRST_TO,
    "odds_corner_handicap": Market.CORNER_HANDICAP,
    "odds_corner_team": Market.CORNER_TEAM,
    "odds_corner_total": Market.CORNER_TOTAL,
    "odds_goals_both_teams": Market.GOALS_BOTH_TEAMS,
    "odds_goals_exact": Market.GOALS_EXACT,
    "odds_goals_over_under": Market.GOALS_OVER_UNDER,
    "odds_goals_team": Market.GOALS_TEAM,
    "odds_cards_team": Market.CARDS_TEAM,
    "odds_cards_total": Market.CARDS_TOTAL,
    "odds_halves_over_under": Market.HALVES_OVER_UNDER,
    "odds_match_1x2": Market.MATCH_1X2,
    "odds_match_double_chance": Market.MATCH_DOUBLE_CHANCE,
    "odds_multigol": Market.MULTIGOL,
    "odds_multigol_team": Market.MULTIGOL_TEAM,
    "odds_score_exact": Market.SCORE_EXACT,
    "odds_score_ht_ft": Market.SCORE_HT_FT,
    "odds_shots_on_target_total": Market.SHOTS_TOTAL,
    "odds_shots_total": Market.SHOTS_ON_TARGET_TOTAL,
    "odds_combo_1x2_over_under": Market.COMBO_1X2_OVER_UNDER,
    "odds_combo_btts_over_under": Market.COMBO_BTTS_OVER_UNDER,
}


class LegacyOddsImportError(ValueError):
    """Raised when a legacy row cannot be mapped to an ``OddsSnapshot``."""


def _parse_legacy_date(raw: str) -> datetime:
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise LegacyOddsImportError(f"unparseable date {raw!r}")


def _extract_params(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """Pull market-specific params from a legacy row.

    :param table: legacy table name
    :param row: row as a ``dict`` keyed by column name
    :return: JSON-serializable param dict for this market
    """
    params: dict[str, Any] = {}
    for key in ("threshold", "threshold_1", "threshold_2", "handicap", "team"):
        if key in row and row[key] not in (None, ""):
            params[key] = row[key]
    if "target_corners" in row and row["target_corners"] not in (None, ""):
        params["target_corners"] = int(row["target_corners"])
    if "result_1x2" in row and row["result_1x2"] not in (None, ""):
        params["result_1x2"] = row["result_1x2"]
    if "bet_btts" in row and row["bet_btts"] not in (None, ""):
        params["bet_btts"] = row["bet_btts"]
    if "bet_ou" in row and row["bet_ou"] not in (None, ""):
        params["bet_ou"] = row["bet_ou"]
    del table
    return params


def _extract_selection(row: dict[str, Any]) -> str:
    if "bet" not in row:
        raise LegacyOddsImportError("row has no 'bet' column")
    value = row["bet"]
    if value is None or value == "":
        raise LegacyOddsImportError("empty 'bet' selection")
    return str(value)


def iter_legacy_rows(
    sqlite_path: str,
    *,
    only_tables: list[str] | None = None,
    require_match: bool = True,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(table, row)`` tuples from every known legacy odds table.

    :param sqlite_path: path to the legacy ``betting_odds.db``
    :param only_tables: restrict to these table names (useful in tests)
    :param require_match: skip rows whose ``match`` or ``date`` field is empty
    :yield: one legacy row at a time
    """
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        existing = {
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table, _market in LEGACY_TABLE_TO_MARKET.items():
            if table not in existing:
                continue
            if only_tables is not None and table not in only_tables:
                continue
            for row in cur.execute(f"SELECT * FROM {table}").fetchall():
                d = dict(row)
                if require_match and (
                    not d.get("match") or not d.get("date")
                ):
                    continue
                yield table, d
    finally:
        conn.close()


def legacy_row_to_snapshot(
    table: str, row: dict[str, Any], *, run_id: str
) -> OddsSnapshot:
    """Convert one legacy row into an :class:`OddsSnapshot`.

    :param table: source table name
    :param row: row columns as a plain dict
    :param run_id: provenance identifier attached to every emitted snapshot
    :return: fully validated :class:`OddsSnapshot`
    """
    if table not in LEGACY_TABLE_TO_MARKET:
        raise LegacyOddsImportError(f"unknown legacy table {table!r}")
    market = LEGACY_TABLE_TO_MARKET[table]

    match_label_raw = str(row["match"]).strip()
    home, away = split_match_string(canonicalize_match_string(match_label_raw))
    match_date = _parse_legacy_date(str(row["date"]))
    season = Season.from_legacy(str(row["season"]).strip()).code

    bookmaker_raw = str(row["bookmaker"]).strip().lower()
    try:
        bookmaker = Bookmaker(bookmaker_raw)
    except ValueError as e:
        raise LegacyOddsImportError(
            f"unknown legacy bookmaker {bookmaker_raw!r}"
        ) from e

    payout = float(row["payout"])
    if payout <= 0:
        raise LegacyOddsImportError(f"non-positive payout {payout}")

    captured = datetime.combine(match_date.date(), time.min, tzinfo=timezone.utc)

    bookmaker_event_id = f"legacy:{bookmaker.value}:{match_date.date().isoformat()}:{home}-{away}"

    return OddsSnapshot(
        bookmaker=bookmaker,
        bookmaker_event_id=bookmaker_event_id,
        match_id=None,
        match_label=f"{home}-{away}",
        match_date=match_date.date(),
        season=season,
        league=None,
        home_team=home,
        away_team=away,
        market=market,
        market_params=_extract_params(table, row),
        selection=_extract_selection(row),
        payout=payout,
        captured_at=captured,
        source=f"legacy_sqlite:{table}",
        run_id=run_id,
        raw_json=json.dumps(row, sort_keys=True, default=str),
    )


def legacy_rows_to_snapshots(
    sqlite_path: str,
    *,
    run_id: str | None = None,
    only_tables: list[str] | None = None,
) -> tuple[list[OddsSnapshot], dict[str, int]]:
    """Convert every importable row in a legacy DB to ``OddsSnapshot`` objects.

    :param sqlite_path: path to the legacy ``betting_odds.db``
    :param run_id: provenance identifier; generated if not provided
    :param only_tables: restrict to these table names (useful in tests)
    :return: ``(snapshots, rejected_reasons)``
    """
    run_id = run_id or f"legacy_import:{uuid.uuid4()}"
    snapshots: list[OddsSnapshot] = []
    rejected: dict[str, int] = {}
    for table, row in iter_legacy_rows(sqlite_path, only_tables=only_tables):
        try:
            snapshots.append(legacy_row_to_snapshot(table, row, run_id=run_id))
        except (LegacyOddsImportError, ValueError) as e:
            key = f"{table}:{type(e).__name__}"
            rejected[key] = rejected.get(key, 0) + 1
    return snapshots, rejected
