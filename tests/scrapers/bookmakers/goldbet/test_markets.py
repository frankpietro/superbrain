"""Fixture-driven assertions for :mod:`superbrain.scrapers.bookmakers.goldbet.markets`."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

import pytest

from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League, OddsSnapshot
from superbrain.scrapers.bookmakers.goldbet.markets import (
    EventMeta,
    build_event_meta,
    infer_season,
    make_unmapped_log,
    parse_event_datetime,
    parse_markets,
    split_event_name,
)


def _by_market(snaps: Iterable[OddsSnapshot], market: Market) -> list[OddsSnapshot]:
    return [s for s in snaps if s.market == market]


class TestHelpers:
    def test_parse_event_datetime_ok(self) -> None:
        dt = parse_event_datetime("24-04-2026 20:45")
        assert dt == datetime(2026, 4, 24, 20, 45)

    @pytest.mark.parametrize(
        "raw",
        ["", "not a date", "2026-04-24 20:45", "24-04-2026T20:45"],
    )
    def test_parse_event_datetime_bad(self, raw: str) -> None:
        assert parse_event_datetime(raw) is None

    def test_split_event_name_canonicalizes(self) -> None:
        home, away = split_event_name("Napoli - Cremonese")
        assert home == "Napoli"
        assert away == "Cremonese"

    def test_split_event_name_missing_separator(self) -> None:
        home, away = split_event_name("Napoli")
        assert home == "Napoli"
        assert away == ""

    @pytest.mark.parametrize(
        "match_date,expected",
        [
            (date(2026, 4, 24), "2025-26"),
            (date(2025, 8, 10), "2025-26"),
            (date(2025, 7, 31), "2024-25"),
            (date(2019, 12, 31), "2019-20"),
        ],
    )
    def test_infer_season(self, match_date: date, expected: str) -> None:
        assert infer_season(match_date) == expected


class TestBuildEventMeta:
    def test_happy_path(self, markets_tab0: dict[str, Any], captured_at: datetime) -> None:
        meta = build_event_meta(
            markets_tab0["leo"][0],
            captured_at=captured_at,
            source="test",
            run_id="r1",
        )
        assert meta is not None
        assert meta.bookmaker_event_id == "15408447"
        assert meta.home_team == "Napoli"
        assert meta.away_team == "Cremonese"
        assert meta.league == League.SERIE_A
        assert meta.season == "2025-26"
        # match_id is populated when league is known
        assert meta.match_id is not None
        assert len(meta.match_id) == 16

    def test_returns_none_when_date_unparseable(self, captured_at: datetime) -> None:
        assert (
            build_event_meta(
                {"ei": 1, "en": "A - B", "ed": "garbage", "ti": 93},
                captured_at=captured_at,
                source="x",
                run_id="y",
            )
            is None
        )


class TestPrincipaliParsing:
    def test_basic_market_families_present(
        self, markets_tab0: dict[str, Any], event_meta: EventMeta
    ) -> None:
        snaps = list(parse_markets(markets_tab0, event_meta))
        assert len(snaps) > 0
        kinds = {s.market for s in snaps}
        # Principali reliably includes 1X2, DC, BTTS, O/U, score-exact
        assert Market.MATCH_1X2 in kinds
        assert Market.MATCH_DOUBLE_CHANCE in kinds
        assert Market.GOALS_BOTH_TEAMS in kinds
        assert Market.GOALS_OVER_UNDER in kinds
        assert Market.SCORE_EXACT in kinds

    def test_snapshot_fields(self, markets_tab0: dict[str, Any], event_meta: EventMeta) -> None:
        snaps = list(parse_markets(markets_tab0, event_meta))
        for s in snaps:
            assert s.bookmaker is Bookmaker.GOLDBET
            assert s.bookmaker_event_id == "15408447"
            assert s.payout > 0
            assert s.captured_at.tzinfo is not None

    def test_1x2_exact_selections(
        self, markets_tab0: dict[str, Any], event_meta: EventMeta
    ) -> None:
        snaps = _by_market(parse_markets(markets_tab0, event_meta), Market.MATCH_1X2)
        selections = {s.selection for s in snaps}
        assert selections == {"1", "X", "2"}

    def test_double_chance_selections(
        self, markets_tab0: dict[str, Any], event_meta: EventMeta
    ) -> None:
        snaps = _by_market(parse_markets(markets_tab0, event_meta), Market.MATCH_DOUBLE_CHANCE)
        assert {s.selection for s in snaps} == {"1X", "12", "X2"}

    def test_btts_yes_no(self, markets_tab0: dict[str, Any], event_meta: EventMeta) -> None:
        snaps = _by_market(parse_markets(markets_tab0, event_meta), Market.GOALS_BOTH_TEAMS)
        assert {s.selection for s in snaps} == {"YES", "NO"}

    def test_goals_over_under_threshold_param(
        self, markets_tab0: dict[str, Any], event_meta: EventMeta
    ) -> None:
        snaps = _by_market(parse_markets(markets_tab0, event_meta), Market.GOALS_OVER_UNDER)
        # Each threshold produces two rows (OVER/UNDER) and thresholds are floats
        thresholds = {s.market_params["threshold"] for s in snaps}
        assert thresholds  # at least one
        assert all(isinstance(t, float) for t in thresholds)
        # A 2.5 threshold should be present for Serie A top-flight events
        assert 2.5 in thresholds
        for s in snaps:
            assert s.selection in {"OVER", "UNDER"}

    def test_combo_1x2_over_under(
        self, markets_tab0: dict[str, Any], event_meta: EventMeta
    ) -> None:
        snaps = _by_market(parse_markets(markets_tab0, event_meta), Market.COMBO_1X2_OVER_UNDER)
        assert snaps
        for s in snaps:
            assert s.market_params["result_1x2"] in {"1", "X", "2"}
            assert s.selection in {"OVER", "UNDER"}
            assert isinstance(s.market_params["threshold"], float)

    def test_combo_btts_over_under(
        self, markets_tab0: dict[str, Any], event_meta: EventMeta
    ) -> None:
        snaps = _by_market(parse_markets(markets_tab0, event_meta), Market.COMBO_BTTS_OVER_UNDER)
        assert snaps
        for s in snaps:
            assert s.market_params["bet_btts"] in {"YES", "NO"}
            assert s.selection in {"OVER", "UNDER"}

    def test_score_exact(self, markets_tab0: dict[str, Any], event_meta: EventMeta) -> None:
        snaps = _by_market(parse_markets(markets_tab0, event_meta), Market.SCORE_EXACT)
        assert snaps
        for s in snaps:
            assert ":" in s.selection
            assert isinstance(s.market_params["home"], int)
            assert isinstance(s.market_params["away"], int)

    def test_score_ht_ft(self, markets_tab0: dict[str, Any], event_meta: EventMeta) -> None:
        snaps = _by_market(parse_markets(markets_tab0, event_meta), Market.SCORE_HT_FT)
        assert len(snaps) == 9
        for s in snaps:
            assert s.market_params["ht"] in {"1", "X", "2"}
            assert s.market_params["ft"] in {"1", "X", "2"}

    def test_halves_ou(self, markets_tab0: dict[str, Any], event_meta: EventMeta) -> None:
        snaps = _by_market(parse_markets(markets_tab0, event_meta), Market.HALVES_OVER_UNDER)
        assert snaps
        halves = {s.market_params["half"] for s in snaps}
        assert halves <= {1, 2}

    def test_corner_total_from_principali(
        self, markets_tab0: dict[str, Any], event_meta: EventMeta
    ) -> None:
        snaps = _by_market(parse_markets(markets_tab0, event_meta), Market.CORNER_TOTAL)
        # Principali includes "U/O Angoli" with multiple thresholds
        assert snaps
        assert all(s.selection in {"OVER", "UNDER"} for s in snaps)


class TestAngoliTab:
    def test_corner_total_yields_both_sides(
        self, markets_tab_angoli: dict[str, Any], captured_at: datetime
    ) -> None:
        meta = build_event_meta(
            markets_tab_angoli["leo"][0],
            captured_at=captured_at,
            source="t",
            run_id="r",
        )
        assert meta is not None
        snaps = list(parse_markets(markets_tab_angoli, meta))
        totals = _by_market(snaps, Market.CORNER_TOTAL)
        thresholds = {s.market_params["threshold"] for s in totals}
        assert thresholds == {8.5, 9.5}
        assert {s.selection for s in totals} == {"OVER", "UNDER"}


class TestMultigolTab:
    def test_multigol_total_and_team(
        self, markets_tab_multigol: dict[str, Any], captured_at: datetime
    ) -> None:
        meta = build_event_meta(
            markets_tab_multigol["leo"][0],
            captured_at=captured_at,
            source="t",
            run_id="r",
            league_hint=League.SERIE_A,
        )
        assert meta is not None
        snaps = list(parse_markets(markets_tab_multigol, meta))

        total = _by_market(snaps, Market.MULTIGOL)
        team = _by_market(snaps, Market.MULTIGOL_TEAM)
        assert total
        assert team
        for s in total:
            assert s.market_params["lower"] == 1
        team_names = {s.market_params["team"] for s in team}
        # Goldbet uses Italian Casa/Ospite; we canonicalize via the meta.home/away
        assert meta.home_team in team_names
        assert meta.away_team in team_names


class TestFailureTolerance:
    def test_empty_payload_returns_no_snapshots(self, event_meta: EventMeta) -> None:
        assert list(parse_markets({}, event_meta)) == []
        assert list(parse_markets({"leo": []}, event_meta)) == []

    def test_rejects_non_positive_payout(self, event_meta: EventMeta) -> None:
        payload = {
            "leo": [
                {
                    "en": "Home - Away",
                    "ed": "24-04-2026 20:45",
                    "mmkW": {
                        "x;1;1;0;0": {
                            "mn": "1X2",
                            "smk": False,
                            "spd": {
                                "0": {
                                    "asl": [
                                        {"sn": "1", "ov": 0},
                                        {"sn": "X", "ov": -1.5},
                                        {"sn": "2", "ov": 2.4},
                                    ]
                                }
                            },
                        }
                    },
                }
            ]
        }
        snaps = list(parse_markets(payload, event_meta))
        # Only the 2.4 payout survives
        assert len(snaps) == 1
        assert snaps[0].selection == "2"
        assert snaps[0].payout == pytest.approx(2.4)

    def test_unknown_market_logged_once(self, event_meta: EventMeta) -> None:
        payload = {
            "leo": [
                {
                    "en": "Home - Away",
                    "ed": "24-04-2026 20:45",
                    "mmkW": {
                        "x;1;1;0;0": {
                            "mn": "Spike Totally Unknown Market",
                            "smk": False,
                            "spd": {"0": {"asl": [{"sn": "A", "ov": 1.5}]}},
                        },
                        "x;2;2;0;0": {
                            "mn": "Spike Totally Unknown Market",
                            "smk": False,
                            "spd": {"0": {"asl": [{"sn": "B", "ov": 2.0}]}},
                        },
                    },
                }
            ]
        }
        unmapped = make_unmapped_log()
        assert list(parse_markets(payload, event_meta, unmapped=unmapped)) == []
        assert "Spike Totally Unknown Market" in unmapped.seen

    def test_one_bad_block_does_not_poison_siblings(self, event_meta: EventMeta) -> None:
        payload = {
            "leo": [
                {
                    "en": "A - B",
                    "ed": "24-04-2026 20:45",
                    "mmkW": {
                        "x;1;1;0;0": {
                            "mn": "1X2",
                            "smk": False,
                            "spd": "not a dict",  # broken block
                        },
                        "x;2;2;0;0": {
                            "mn": "GG/NG",
                            "smk": False,
                            "spd": {
                                "0": {
                                    "asl": [
                                        {"sn": "GG", "ov": 1.6},
                                        {"sn": "NG", "ov": 2.3},
                                    ]
                                }
                            },
                        },
                    },
                }
            ]
        }
        snaps = list(parse_markets(payload, event_meta))
        assert {s.selection for s in snaps} == {"YES", "NO"}
