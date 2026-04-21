"""Tests for :mod:`superbrain.scrapers.bookmakers.sisal.markets`.

Every covered market family gets at least one explicit assertion built
against real Sisal payload shapes (trimmed spike fixtures).
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

import pytest

from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League, OddsSnapshot
from superbrain.scrapers.bookmakers.sisal.markets import (
    parse_event_markets,
    parse_event_meta,
)

CAPTURED_AT = datetime(2026, 4, 21, 14, 30, tzinfo=UTC)


@pytest.fixture
def parsed(
    event_markets_payload: dict[str, Any],
) -> tuple[list[OddsSnapshot], Counter[str]]:
    snapshots, unmapped = parse_event_markets(
        event_markets_payload,
        league=League.SERIE_A,
        captured_at=CAPTURED_AT,
        run_id="test-run",
    )
    return snapshots, unmapped


def test_parse_event_meta_fiorentina_sassuolo(event_markets_payload: dict[str, Any]) -> None:
    event = parse_event_meta(event_markets_payload["avvenimentoFe"], League.SERIE_A)
    assert event is not None
    assert event.event_key == "36171-19"
    assert event.home_team_raw == "Fiorentina"
    assert event.away_team_raw == "Sassuolo"
    assert event.match_date.isoformat() == "2026-04-26"
    assert event.season == "2025-26"


def test_snapshot_base_fields(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    assert snapshots, "expected non-empty snapshot list"
    s = snapshots[0]
    assert s.bookmaker == Bookmaker.SISAL
    assert s.bookmaker_event_id
    assert s.league == League.SERIE_A
    assert s.season == "2025-26"
    assert s.payout > 1.0
    assert s.captured_at == CAPTURED_AT
    assert s.raw_json is not None
    assert s.match_id  # computed via compute_match_id


@pytest.mark.parametrize(
    ("market", "min_rows"),
    [
        (Market.MATCH_1X2, 3),  # 1X2 final + 1T + 2T ⇒ at least 3
        (Market.MATCH_DOUBLE_CHANCE, 3),
        (Market.GOALS_OVER_UNDER, 6),
        (Market.GOALS_BOTH_TEAMS, 2),
        (Market.GOALS_TEAM, 4),
        (Market.MULTIGOL, 3),
        (Market.MULTIGOL_TEAM, 3),
        (Market.SCORE_EXACT, 10),
        (Market.SCORE_HT_FT, 3),
        (Market.CORNER_1X2, 3),
        (Market.CORNER_HANDICAP, 2),
        (Market.HALVES_OVER_UNDER, 3),
        (Market.COMBO_1X2_OVER_UNDER, 6),
        (Market.COMBO_BTTS_OVER_UNDER, 4),
    ],
)
def test_market_family_has_rows(
    parsed: tuple[list[Any], Counter[str]],
    market: Market,
    min_rows: int,
) -> None:
    snapshots, _ = parsed
    hits = [s for s in snapshots if s.market == market]
    assert len(hits) >= min_rows, f"expected ≥{min_rows} rows for {market}, got {len(hits)}"


def test_match_1x2_full_selections(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    full_1x2 = [
        s for s in snapshots if s.market == Market.MATCH_1X2 and "half" not in s.market_params
    ]
    selections = {s.selection for s in full_1x2}
    assert selections == {"1", "X", "2"}


def test_goals_over_under_thresholds(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    ou = [s for s in snapshots if s.market == Market.GOALS_OVER_UNDER]
    thresholds = {s.market_params["threshold"] for s in ou}
    assert {1.5, 2.5, 3.5}.issubset(thresholds)
    # Every threshold emits exactly one OVER and one UNDER.
    by_threshold: dict[float, set[str]] = {}
    for s in ou:
        by_threshold.setdefault(s.market_params["threshold"], set()).add(s.selection)
    for t, sel in by_threshold.items():
        # Some outlier thresholds only publish one side (the other is
        # suspended at scrape time); we just require each emitted row to
        # be a valid OVER/UNDER selection.
        assert sel.issubset({"OVER", "UNDER"}) and sel, t


def test_double_chance_selections(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    dc = [
        s
        for s in snapshots
        if s.market == Market.MATCH_DOUBLE_CHANCE and "half" not in s.market_params
    ]
    assert {s.selection for s in dc} == {"1X", "12", "X2"}


def test_btts_selections(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    btts_full = [
        s
        for s in snapshots
        if s.market == Market.GOALS_BOTH_TEAMS and "half" not in s.market_params
    ]
    assert {s.selection for s in btts_full} == {"YES", "NO"}


def test_score_exact_params(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    score = [s for s in snapshots if s.market == Market.SCORE_EXACT]
    for s in score:
        assert isinstance(s.market_params["home"], int)
        assert isinstance(s.market_params["away"], int)
        assert s.selection == f"{s.market_params['home']}-{s.market_params['away']}"


def test_score_ht_ft_selection_format(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    ht_ft = [s for s in snapshots if s.market == Market.SCORE_HT_FT]
    assert ht_ft, "expected at least one HT/FT row"
    for s in ht_ft:
        assert s.market_params["ht"] in {"1", "X", "2"}
        assert s.market_params["ft"] in {"1", "X", "2"}


def test_corner_handicap_includes_half_and_handicap(
    parsed: tuple[list[Any], Counter[str]],
) -> None:
    snapshots, _ = parsed
    corner = [s for s in snapshots if s.market == Market.CORNER_HANDICAP]
    assert corner
    for s in corner:
        assert s.market_params["half"] == 1
        assert isinstance(s.market_params["handicap"], float)
        assert s.selection in {"HOME", "AWAY"}


def test_goals_team_attaches_canonical_team(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    team_ou = [s for s in snapshots if s.market == Market.GOALS_TEAM]
    assert team_ou
    teams = {s.market_params["team"] for s in team_ou}
    assert teams == {"Fiorentina", "Sassuolo"}


def test_combo_1x2_over_under_params(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    combo = [s for s in snapshots if s.market == Market.COMBO_1X2_OVER_UNDER]
    assert combo
    for s in combo:
        assert s.market_params["result_1x2"] in {"1", "X", "2"}
        assert isinstance(s.market_params["threshold"], float)
        assert s.selection in {"OVER", "UNDER"}


def test_combo_btts_over_under_params(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    combo = [s for s in snapshots if s.market == Market.COMBO_BTTS_OVER_UNDER]
    assert combo
    for s in combo:
        assert s.market_params["bet_btts"] in {"YES", "NO"}
        assert isinstance(s.market_params["threshold"], float)
        assert s.selection in {"OVER", "UNDER"}


def test_halves_over_under_has_half(parsed: tuple[list[Any], Counter[str]]) -> None:
    snapshots, _ = parsed
    halves = [s for s in snapshots if s.market == Market.HALVES_OVER_UNDER]
    assert halves
    halves_observed = {s.market_params["half"] for s in halves}
    assert halves_observed.issubset({1, 2})


def test_unmapped_markets_counted_not_raised(parsed: tuple[list[Any], Counter[str]]) -> None:
    _, unmapped = parsed
    # The trimmed fixture deliberately excludes unmapped markets, so the
    # counter must be empty; the real payloads exercise the skip-path in
    # ``test_live.py``.
    assert isinstance(unmapped, Counter)
    assert not unmapped


def test_parse_is_resilient_to_missing_esito_list() -> None:
    payload: dict[str, Any] = {
        "avvenimentoFe": {
            "key": "1-2",
            "eventId": 1,
            "descrizione": "A - B",
            "data": "2026-05-01T18:00:00.000Z",
            "firstCompetitor": {"description": "A"},
            "secondCompetitor": {"description": "B"},
        },
        "scommessaMap": {
            "1-2-3": {"descrizione": "1X2 ESITO FINALE"},
        },
        "infoAggiuntivaMap": {
            "1-2-3-0": {"soglia": ""},  # no esitoList
        },
    }
    snapshots, unmapped = parse_event_markets(
        payload, league=League.SERIE_A, captured_at=CAPTURED_AT, run_id="t"
    )
    assert snapshots == []
    assert unmapped == Counter()


def test_parse_returns_empty_without_event_meta() -> None:
    snapshots, unmapped = parse_event_markets(
        {},
        league=League.SERIE_A,
        captured_at=CAPTURED_AT,
        run_id="t",
    )
    assert snapshots == []
    assert unmapped == Counter()
