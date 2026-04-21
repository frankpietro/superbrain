"""Tests for the market registry."""

from __future__ import annotations

import pytest

from superbrain.core.markets import MARKET_METADATA, Market, metadata_for


class TestMarketRegistry:
    def test_every_enum_member_has_metadata(self) -> None:
        missing = set(Market) - set(MARKET_METADATA)
        assert not missing, f"markets missing metadata: {missing}"

    def test_metadata_keyed_consistently(self) -> None:
        for code, meta in MARKET_METADATA.items():
            assert meta.code is code

    def test_metadata_for_accepts_string_or_enum(self) -> None:
        assert metadata_for("corner_total") is MARKET_METADATA[Market.CORNER_TOTAL]
        assert metadata_for(Market.CORNER_TOTAL) is MARKET_METADATA[Market.CORNER_TOTAL]

    def test_metadata_for_rejects_unknown(self) -> None:
        with pytest.raises(ValueError):
            metadata_for("not_a_market")


class TestMarketMetadata:
    @pytest.mark.parametrize("market", list(Market))
    def test_selections_and_params_are_tuples(self, market: Market) -> None:
        meta = MARKET_METADATA[market]
        assert isinstance(meta.selections, tuple)
        assert isinstance(meta.param_keys, tuple)
