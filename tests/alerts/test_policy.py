"""Table-driven tests for :class:`AlertPolicy`.

The policy is a pure filter: no I/O, no clock, no network. Every test
here composes one or more :class:`ValueBet` objects, runs them through
an :class:`AlertPolicy`, and asserts on ``admitted`` plus the
per-reason rejection map.
"""

from __future__ import annotations

from dataclasses import replace as dataclass_replace
from datetime import date
from typing import Any

import pytest

from superbrain.alerts.config import AlertSettings
from superbrain.alerts.models import AlertRecord
from superbrain.alerts.policy import AlertPolicy, RejectionReason
from superbrain.core.markets import Market
from superbrain.engine.pipeline import ValueBet
from tests.alerts.conftest import make_match, make_value_bet


class TestEdgeThreshold:
    def test_high_edge_is_admitted(self, default_settings: AlertSettings) -> None:
        policy = AlertPolicy(default_settings)
        assert policy.should_alert(make_value_bet(edge=0.08)) is True
        assert len(policy.admitted) == 1

    def test_exactly_at_threshold_is_admitted(self, default_settings: AlertSettings) -> None:
        policy = AlertPolicy(default_settings)
        assert policy.should_alert(make_value_bet(edge=0.05)) is True

    def test_below_threshold_is_rejected(self, default_settings: AlertSettings) -> None:
        policy = AlertPolicy(default_settings)
        vb = make_value_bet(edge=0.049)
        assert policy.should_alert(vb) is False
        assert policy.admitted == []
        reasons = list(policy.rejections.values())
        assert len(reasons) == 1
        assert reasons[0].kind == "edge_below_threshold"


class TestMinProbability:
    def test_above_floor(self, default_settings: AlertSettings) -> None:
        policy = AlertPolicy(default_settings)
        assert policy.should_alert(make_value_bet(probability=0.45)) is True

    def test_below_floor_rejected(self, default_settings: AlertSettings) -> None:
        policy = AlertPolicy(default_settings)
        vb = make_value_bet(probability=0.20, edge=0.10)
        assert policy.should_alert(vb) is False
        reasons = list(policy.rejections.values())
        assert reasons[0].kind == "probability_below_floor"


class TestPerMatchCap:
    def test_cap_limits_alerts_on_single_match(self, default_settings: AlertSettings) -> None:
        fixture = make_match()
        bets = [
            make_value_bet(fixture=fixture, selection=sel, odds=1.90 + 0.01 * i)
            for i, sel in enumerate(("OVER", "UNDER", "YES", "NO"))
        ]
        policy = AlertPolicy(default_settings)
        results = [policy.should_alert(vb) for vb in bets]
        assert results.count(True) == default_settings.alert_per_match_cap
        assert results[-1] is False
        last_id = AlertRecord.from_value_bet(bets[-1]).alert_id
        assert policy.rejections[last_id].kind == "per_match_cap"

    def test_cap_is_per_match_not_global(self, default_settings: AlertSettings) -> None:
        match_a = make_match(home="A", away="B", match_date=date(2025, 5, 18))
        match_b = make_match(home="C", away="D", match_date=date(2025, 5, 18))
        bets = [
            make_value_bet(fixture=match_a, selection="OVER", odds=1.90),
            make_value_bet(fixture=match_a, selection="UNDER", odds=1.95),
            make_value_bet(fixture=match_a, selection="YES", odds=1.80),
            make_value_bet(fixture=match_b, selection="OVER", odds=1.92),
        ]
        policy = AlertPolicy(default_settings)
        for vb in bets:
            policy.should_alert(vb)
        assert len(policy.admitted) == 4


class TestMaxPerRun:
    def test_caps_total_alerts(self, tmp_path: Any) -> None:
        settings = AlertSettings(
            SUPERBRAIN_ALERT_SINK_PATH=tmp_path / "sink.parquet",
            SUPERBRAIN_ALERT_MAX_PER_RUN=2,
            SUPERBRAIN_ALERT_PER_MATCH_CAP=10,
        )
        policy = AlertPolicy(settings)
        for i in range(5):
            vb = make_value_bet(
                fixture=make_match(home=f"H{i}", away=f"A{i}"), odds=1.90 + 0.01 * i
            )
            policy.should_alert(vb)
        assert len(policy.admitted) == 2


class TestDedup:
    def test_alert_id_seen_in_previous_window_is_dropped(
        self, default_settings: AlertSettings
    ) -> None:
        vb = make_value_bet()
        prev_id = AlertRecord.from_value_bet(vb).alert_id
        policy = AlertPolicy(default_settings, previous_alert_ids={prev_id})
        assert policy.should_alert(vb) is False
        assert policy.rejections[prev_id].kind == "dedup"

    def test_distinct_alert_ids_are_kept(self, default_settings: AlertSettings) -> None:
        vb_a = make_value_bet(selection="OVER")
        vb_b = make_value_bet(selection="UNDER", odds=1.95)
        policy = AlertPolicy(default_settings)
        assert policy.should_alert(vb_a) is True
        assert policy.should_alert(vb_b) is True
        assert len({r.alert_id for r in policy.admitted}) == 2

    def test_intra_run_dedup(self, default_settings: AlertSettings) -> None:
        vb = make_value_bet()
        policy = AlertPolicy(default_settings)
        assert policy.should_alert(vb) is True
        # Same value bet a second time in the same sweep is rejected.
        assert policy.should_alert(vb) is False


class TestFilterReturn:
    def test_filter_returns_admitted_in_order(self, default_settings: AlertSettings) -> None:
        bets = [
            make_value_bet(
                fixture=make_match(home=f"H{i}", away=f"A{i}"),
                edge=0.08,
                odds=1.90 + i * 0.01,
            )
            for i in range(3)
        ]
        policy = AlertPolicy(default_settings)
        admitted = policy.filter(bets)
        assert [a.home_team for a in admitted] == ["H0", "H1", "H2"]


@pytest.mark.parametrize(
    "edge,probability,expected_kind",
    [
        (0.04, 0.50, "edge_below_threshold"),
        (0.06, 0.30, "probability_below_floor"),
        (0.02, 0.20, "edge_below_threshold"),
    ],
)
def test_rejection_reasons_table(
    default_settings: AlertSettings,
    edge: float,
    probability: float,
    expected_kind: str,
) -> None:
    policy = AlertPolicy(default_settings)
    vb = make_value_bet(edge=edge, probability=probability)
    assert policy.should_alert(vb) is False
    reason = next(iter(policy.rejections.values()))
    assert isinstance(reason, RejectionReason)
    assert reason.kind == expected_kind


def test_alert_id_stable_across_runs(default_settings: AlertSettings) -> None:
    vb_a: ValueBet = make_value_bet()
    vb_b: ValueBet = dataclass_replace(vb_a)
    assert AlertRecord.from_value_bet(vb_a).alert_id == AlertRecord.from_value_bet(vb_b).alert_id


def test_params_hash_disambiguates_over_under_thresholds(
    default_settings: AlertSettings,
) -> None:
    over_25 = make_value_bet(
        market=Market.GOALS_OVER_UNDER,
        selection="OVER",
        params={"threshold": 2.5},
    )
    over_15 = make_value_bet(
        market=Market.GOALS_OVER_UNDER,
        selection="OVER",
        params={"threshold": 1.5},
    )
    a = AlertRecord.from_value_bet(over_25).alert_id
    b = AlertRecord.from_value_bet(over_15).alert_id
    assert a != b
