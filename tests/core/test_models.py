"""Tests for the pydantic core models."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from superbrain.core.markets import Market
from superbrain.core.models import (
    Bookmaker,
    IngestProvenance,
    IngestReport,
    League,
    Match,
    OddsSnapshot,
    Season,
    compute_match_id,
)


class TestSeason:
    def test_valid_code(self) -> None:
        assert Season(code="2024-25").code == "2024-25"

    def test_invalid_code_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Season(code="abc")

    def test_from_legacy_roundtrip(self) -> None:
        assert Season.from_legacy("2425").code == "2024-25"
        assert Season.from_legacy("9900").code == "1999-00"

    def test_from_legacy_rejects_invalid_length(self) -> None:
        with pytest.raises(ValueError):
            Season.from_legacy("202425")


class TestComputeMatchId:
    def test_deterministic(self) -> None:
        a = compute_match_id("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A)
        b = compute_match_id("Roma", "Lazio", date(2024, 9, 1), "serie_a")
        assert a == b
        assert len(a) == 16

    def test_different_inputs_produce_different_ids(self) -> None:
        a = compute_match_id("Roma", "Lazio", date(2024, 9, 1), League.SERIE_A)
        b = compute_match_id("Lazio", "Roma", date(2024, 9, 1), League.SERIE_A)
        assert a != b


class TestMatch:
    def _make(self, **overrides: Any) -> Match:
        defaults: dict[str, Any] = {
            "league": League.SERIE_A,
            "season": "2024-25",
            "match_date": date(2024, 9, 1),
            "home_team": "Roma",
            "away_team": "Lazio",
            "source": "test",
            "ingested_at": datetime.now(tz=UTC),
        }
        defaults.update(overrides)
        match_id = compute_match_id(
            defaults["home_team"],
            defaults["away_team"],
            defaults["match_date"],
            defaults["league"],
        )
        return Match(match_id=match_id, **defaults)

    def test_valid_match(self) -> None:
        m = self._make()
        assert m.home_team == "Roma"

    def test_id_must_match_hash(self) -> None:
        with pytest.raises(ValidationError):
            Match(
                match_id="0" * 16,
                league=League.SERIE_A,
                season="2024-25",
                match_date=date(2024, 9, 1),
                home_team="Roma",
                away_team="Lazio",
                source="test",
                ingested_at=datetime.now(tz=UTC),
            )

    def test_season_pattern(self) -> None:
        with pytest.raises(ValidationError):
            self._make(season="2024/25")


class TestOddsSnapshot:
    def _base(self, **overrides: Any) -> OddsSnapshot:
        base: dict[str, Any] = {
            "bookmaker": Bookmaker.SISAL,
            "bookmaker_event_id": "sisal:evt:123",
            "match_id": None,
            "match_label": "Roma-Lazio",
            "match_date": date(2024, 9, 1),
            "season": "2024-25",
            "league": None,
            "home_team": "Roma",
            "away_team": "Lazio",
            "market": Market.CORNER_TOTAL,
            "market_params": {"threshold": 9.5},
            "selection": "OVER",
            "payout": 1.85,
            "captured_at": datetime(2024, 9, 1, 12, tzinfo=UTC),
            "source": "test",
            "run_id": "run:abc",
        }
        base.update(overrides)
        return OddsSnapshot(**base)

    def test_valid_snapshot(self) -> None:
        s = self._base()
        assert s.payout == 1.85

    def test_payout_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            self._base(payout=-1.0)

    def test_captured_at_gets_utc_if_naive(self) -> None:
        s = self._base(captured_at=datetime(2024, 9, 1, 12))  # naive
        assert s.captured_at.tzinfo is not None

    def test_params_hash_is_deterministic(self) -> None:
        a = self._base(market_params={"threshold": 9.5, "team": 1})
        b = self._base(market_params={"team": 1, "threshold": 9.5})
        assert a.params_hash() == b.params_hash()

    def test_params_hash_is_sensitive_to_values(self) -> None:
        a = self._base(market_params={"threshold": 9.5})
        b = self._base(market_params={"threshold": 10.5})
        assert a.params_hash() != b.params_hash()

    def test_natural_key_includes_capture_time(self) -> None:
        a = self._base()
        b = self._base(captured_at=datetime(2024, 9, 1, 13, tzinfo=UTC))
        assert a.natural_key() != b.natural_key()


class TestIngestReport:
    def test_merge_accumulates(self) -> None:
        a = IngestReport(
            rows_received=3,
            rows_written=2,
            rows_skipped_duplicate=1,
            partitions_written=["p1"],
        )
        b = IngestReport(
            rows_received=4,
            rows_written=4,
            rejected_reasons={"bad_row": 1},
            partitions_written=["p2"],
        )
        merged = a.merge(b)
        assert merged.rows_received == 7
        assert merged.rows_written == 6
        assert merged.rows_skipped_duplicate == 1
        assert merged.rejected_reasons == {"bad_row": 1}
        assert merged.partitions_written == ["p1", "p2"]


class TestIngestProvenance:
    def test_captured_at_normalized_to_utc(self) -> None:
        p = IngestProvenance(
            source="test",
            run_id="r",
            actor="a",
            captured_at=datetime(2024, 1, 1),
        )
        assert p.captured_at.tzinfo is not None
