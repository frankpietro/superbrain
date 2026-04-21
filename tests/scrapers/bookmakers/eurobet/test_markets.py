"""Fixture-driven tests for the Eurobet market parser."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League, OddsSnapshot
from superbrain.scrapers.bookmakers.eurobet.markets import (
    parse_event_markets,
    parse_event_meta,
)

FIXTURES = Path(__file__).parent.parent.parent.parent / "fixtures" / "bookmakers" / "eurobet"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return data


@pytest.fixture
def captured_at() -> datetime:
    return datetime(2026, 4, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def event_payload() -> dict[str, Any]:
    return _load("event_napoli_cremonese.json")


def _by_market(snaps: list[OddsSnapshot]) -> dict[str, list[OddsSnapshot]]:
    out: dict[str, list[OddsSnapshot]] = {}
    for s in snaps:
        out.setdefault(s.market.value, []).append(s)
    return out


class TestParseEventMeta:
    def test_extracts_core_fields(self, event_payload: dict[str, Any]) -> None:
        event_info = event_payload["result"]["eventInfo"]
        meta = parse_event_meta(event_info, League.SERIE_A)
        assert meta is not None
        assert meta.home_team  # canonicalized
        assert meta.away_team
        assert meta.kickoff.tzinfo == UTC
        assert meta.season.startswith("2025-")  # season for April 2026 matches

    def test_returns_none_on_missing_fields(self) -> None:
        assert parse_event_meta({}, League.SERIE_A) is None
        assert parse_event_meta({"programCode": 1}, League.SERIE_A) is None


class TestParseEventMarkets:
    def test_emits_canonical_market_families(
        self, event_payload: dict[str, Any], captured_at: datetime
    ) -> None:
        snaps, unmapped = parse_event_markets(
            event_payload,
            league=League.SERIE_A,
            captured_at=captured_at,
            run_id="r",
        )
        by_market = _by_market(snaps)
        assert Market.MATCH_1X2.value in by_market
        assert Market.GOALS_OVER_UNDER.value in by_market
        assert Market.GOALS_BOTH_TEAMS.value in by_market
        assert Market.MATCH_DOUBLE_CHANCE.value in by_market
        assert Market.SCORE_HT_FT.value in by_market
        assert isinstance(unmapped, Counter)

    def test_1x2_has_three_selections(
        self, event_payload: dict[str, Any], captured_at: datetime
    ) -> None:
        snaps, _ = parse_event_markets(
            event_payload,
            league=League.SERIE_A,
            captured_at=captured_at,
            run_id="r",
        )
        # Filter to FT 1X2 without handicap or half.
        ft = [
            s
            for s in snaps
            if s.market is Market.MATCH_1X2
            and "half" not in s.market_params
            and "handicap" not in s.market_params
        ]
        selections = {s.selection for s in ft}
        assert selections == {"1", "X", "2"}
        for s in ft:
            assert s.payout > 1.0
            assert s.bookmaker is Bookmaker.EUROBET

    def test_over_under_threshold_is_float(
        self, event_payload: dict[str, Any], captured_at: datetime
    ) -> None:
        snaps, _ = parse_event_markets(
            event_payload,
            league=League.SERIE_A,
            captured_at=captured_at,
            run_id="r",
        )
        ou = [s for s in snaps if s.market is Market.GOALS_OVER_UNDER]
        assert ou
        thresholds = {s.market_params["threshold"] for s in ou}
        assert 2.5 in thresholds
        # both OVER and UNDER surfaces for at least one threshold
        for thr in thresholds:
            sides = {s.selection for s in ou if s.market_params["threshold"] == thr}
            assert sides <= {"OVER", "UNDER"}

    def test_btts_mapped_yes_no(self, event_payload: dict[str, Any], captured_at: datetime) -> None:
        snaps, _ = parse_event_markets(
            event_payload,
            league=League.SERIE_A,
            captured_at=captured_at,
            run_id="r",
        )
        btts = [s for s in snaps if s.market is Market.GOALS_BOTH_TEAMS]
        assert {s.selection for s in btts} == {"YES", "NO"}

    def test_double_chance_canonical_labels(
        self, event_payload: dict[str, Any], captured_at: datetime
    ) -> None:
        snaps, _ = parse_event_markets(
            event_payload,
            league=League.SERIE_A,
            captured_at=captured_at,
            run_id="r",
        )
        dc = [s for s in snaps if s.market is Market.MATCH_DOUBLE_CHANCE]
        assert {s.selection for s in dc} == {"1X", "X2", "12"}

    def test_1x2_handicap_attaches_param(
        self, event_payload: dict[str, Any], captured_at: datetime
    ) -> None:
        snaps, _ = parse_event_markets(
            event_payload,
            league=League.SERIE_A,
            captured_at=captured_at,
            run_id="r",
        )
        hcp = [s for s in snaps if s.market is Market.MATCH_1X2 and "handicap" in s.market_params]
        assert hcp
        for s in hcp:
            assert isinstance(s.market_params["handicap"], float)

    def test_all_payouts_positive_and_json_roundtrip(
        self, event_payload: dict[str, Any], captured_at: datetime
    ) -> None:
        snaps, _ = parse_event_markets(
            event_payload,
            league=League.SERIE_A,
            captured_at=captured_at,
            run_id="r",
        )
        for s in snaps:
            assert s.payout > 1.0
            assert s.raw_json
            assert json.loads(s.raw_json)

    def test_match_id_is_deterministic(
        self, event_payload: dict[str, Any], captured_at: datetime
    ) -> None:
        snaps1, _ = parse_event_markets(
            event_payload,
            league=League.SERIE_A,
            captured_at=captured_at,
            run_id="r",
        )
        snaps2, _ = parse_event_markets(
            event_payload,
            league=League.SERIE_A,
            captured_at=captured_at,
            run_id="r",
        )
        assert snaps1
        ids1 = {s.match_id for s in snaps1}
        ids2 = {s.match_id for s in snaps2}
        assert ids1 == ids2 and len(ids1) == 1

    def test_unknown_bet_id_goes_to_unmapped(self, captured_at: datetime) -> None:
        payload: dict[str, Any] = {
            "result": {
                "eventInfo": {
                    "programCode": 1,
                    "eventCode": 2,
                    "eventData": 1777056300000,
                    "aliasUrl": "x-y-202604242045",
                    "teamHome": {"description": "Napoli"},
                    "teamAway": {"description": "Cremonese"},
                },
                "betGroupList": [
                    {
                        "betId": 999999,
                        "betDescription": "MARKET WE DO NOT KNOW",
                        "oddGroupList": [],
                    }
                ],
            }
        }
        snaps, unmapped = parse_event_markets(
            payload, league=League.SERIE_A, captured_at=captured_at, run_id="r"
        )
        assert snaps == []
        assert unmapped["MARKET WE DO NOT KNOW"] == 1

    def test_missing_result_returns_empty(self, captured_at: datetime) -> None:
        snaps, unmapped = parse_event_markets(
            {"code": -1}, league=League.SERIE_A, captured_at=captured_at, run_id="r"
        )
        assert snaps == []
        assert not unmapped

    def test_score_ht_ft_emits_pairs(
        self, event_payload: dict[str, Any], captured_at: datetime
    ) -> None:
        snaps, _ = parse_event_markets(
            event_payload,
            league=League.SERIE_A,
            captured_at=captured_at,
            run_id="r",
        )
        htft = [s for s in snaps if s.market is Market.SCORE_HT_FT]
        assert htft
        for s in htft:
            assert set(s.market_params) == {"ht", "ft"}
            assert s.market_params["ht"] in {"1", "X", "2"}
            assert s.market_params["ft"] in {"1", "X", "2"}
