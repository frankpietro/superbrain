"""Per-strategy unit tests for every registered ``BetStrategy``.

For each market that has a strategy registered in ``BET_REGISTRY`` this
module asserts two invariants:

1. ``iter_outcomes`` covers every selection the strategy emits -- i.e.
   every ``(selection, params_hash)`` seeded into the snapshot list
   appears in the materialized :class:`Outcome` stream.
2. ``compute_probability`` returns a probability in ``(0, 1]`` on a
   hand-constructed neighbour sample, proving the strategy actually
   prices the outcomes it emits.

These are the phase-4b follow-ups from ``docs/knowledge.md`` -- "Phase
4a follow-ups" -- item (3).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

import superbrain.engine.bets  # noqa: F401 -- ensure @register decorators fire
from superbrain.core.markets import Market
from superbrain.core.models import Bookmaker, League, OddsSnapshot
from superbrain.engine.bets import BET_REGISTRY, registered_markets, strategy_for

SAMPLE_HOME: list[float] = [3.0] * 6
SAMPLE_AWAY: list[float] = [2.0] * 6
"""Deterministic neighbour sample.

Values are chosen so that at least one outcome per strategy yields a
strictly positive probability: the pair ``home=3, away=2`` satisfies
``home > away``, ``home + away >= 4``, and ``both > 0`` -- enough to
exercise 1X2, over/under, BTTS, team over/under, handicap, and combo
strategies in a single pass.
"""


def _params_hash(params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _base_snapshot_kwargs() -> dict[str, Any]:
    return {
        "bookmaker": Bookmaker.SISAL,
        "bookmaker_event_id": "evt-test",
        "match_id": "m" * 16,
        "match_label": "Alpha-Bravo",
        "match_date": date(2024, 3, 1),
        "season": "2023-24",
        "league": League.SERIE_A,
        "home_team": "Alpha",
        "away_team": "Bravo",
        "captured_at": datetime(2024, 2, 29, 12, 0, tzinfo=UTC),
        "source": "unit-test",
        "run_id": "unit-test-run",
    }


def _snap(market: Market, selection: str, params: dict[str, Any], payout: float) -> OddsSnapshot:
    return OddsSnapshot(
        market=market,
        market_params=params,
        selection=selection,
        payout=payout,
        **_base_snapshot_kwargs(),
    )


_CORNER_COMBO_PARAMS = {"threshold_1": 2.5, "threshold_2": 1.5}

_SEED_RECIPES: dict[Market, list[tuple[str, dict[str, Any], float]]] = {
    Market.CARDS_TOTAL: [
        ("OVER", {"threshold": 3.5}, 1.85),
        ("UNDER", {"threshold": 3.5}, 1.95),
    ],
    Market.CORNER_1X2: [
        ("1", {}, 2.10),
        ("X", {}, 3.30),
        ("2", {}, 3.20),
    ],
    Market.CORNER_COMBO: [
        ("OVER+OVER", _CORNER_COMBO_PARAMS, 3.40),
        ("OVER+UNDER", _CORNER_COMBO_PARAMS, 3.60),
        ("UNDER+OVER", _CORNER_COMBO_PARAMS, 3.50),
        ("UNDER+UNDER", _CORNER_COMBO_PARAMS, 4.10),
    ],
    Market.CORNER_HANDICAP: [
        ("HOME", {"handicap": 0.5}, 1.90),
        ("AWAY", {"handicap": 0.5}, 1.95),
    ],
    Market.CORNER_TEAM: [
        ("OVER", {"team": 1, "threshold": 2.5}, 1.80),
        ("UNDER", {"team": 1, "threshold": 2.5}, 2.00),
        ("OVER", {"team": 2, "threshold": 1.5}, 1.70),
        ("UNDER", {"team": 2, "threshold": 1.5}, 2.10),
    ],
    Market.CORNER_TOTAL: [
        ("OVER", {"threshold": 4.5}, 1.85),
        ("UNDER", {"threshold": 4.5}, 1.95),
    ],
    Market.GOALS_BOTH_TEAMS: [
        ("YES", {}, 1.75),
        ("NO", {}, 2.05),
    ],
    Market.GOALS_OVER_UNDER: [
        ("OVER", {"threshold": 2.5}, 1.85),
        ("UNDER", {"threshold": 2.5}, 1.95),
    ],
    Market.GOALS_TEAM: [
        ("OVER", {"team": 1, "threshold": 2.5}, 1.80),
        ("UNDER", {"team": 1, "threshold": 2.5}, 2.00),
        ("OVER", {"team": 2, "threshold": 1.5}, 1.70),
        ("UNDER", {"team": 2, "threshold": 1.5}, 2.10),
    ],
    Market.MATCH_1X2: [
        ("1", {}, 2.20),
        ("X", {}, 3.20),
        ("2", {}, 3.00),
    ],
    Market.MATCH_DOUBLE_CHANCE: [
        ("1X", {}, 1.40),
        ("12", {}, 1.30),
        ("X2", {}, 1.80),
    ],
    Market.SHOTS_TOTAL: [
        ("OVER", {"threshold": 4.5}, 1.85),
        ("UNDER", {"threshold": 4.5}, 1.95),
    ],
    Market.SHOTS_ON_TARGET_TOTAL: [
        ("OVER", {"threshold": 4.5}, 1.85),
        ("UNDER", {"threshold": 4.5}, 1.95),
    ],
}


def _seed_odds_for_market(market: Market) -> list[OddsSnapshot]:
    """Build a set of valid odds rows for every selection a strategy accepts.

    The thresholds are picked so that on the ``(SAMPLE_HOME, SAMPLE_AWAY)``
    neighbour sample at least one selection has strictly positive
    probability -- see the module docstring for the rationale.
    """
    try:
        recipe = _SEED_RECIPES[market]
    except KeyError as exc:
        raise AssertionError(f"no seed recipe for market {market!r}") from exc
    return [_snap(market, sel, params, payout) for sel, params, payout in recipe]


def test_registry_has_expected_coverage() -> None:
    """Phase 4b contract: the 13 strategies shipped in phase 4a are registered.

    Locks down any accidental loss of a strategy module. New strategies
    only require extending this set (and the ``_seed_odds_for_market``
    dispatch above).
    """
    expected = {
        Market.CARDS_TOTAL,
        Market.CORNER_1X2,
        Market.CORNER_COMBO,
        Market.CORNER_HANDICAP,
        Market.CORNER_TEAM,
        Market.CORNER_TOTAL,
        Market.GOALS_BOTH_TEAMS,
        Market.GOALS_OVER_UNDER,
        Market.GOALS_TEAM,
        Market.MATCH_1X2,
        Market.MATCH_DOUBLE_CHANCE,
        Market.SHOTS_TOTAL,
        Market.SHOTS_ON_TARGET_TOTAL,
    }
    assert set(BET_REGISTRY.keys()) == expected


@pytest.mark.parametrize("market", registered_markets(), ids=lambda m: m.value)
def test_iter_outcomes_covers_every_seeded_selection(market: Market) -> None:
    """Every ``(selection, params_hash)`` in the seed must appear as an Outcome."""
    strategy = strategy_for(market)
    snapshots = _seed_odds_for_market(market)

    expected = {(s.selection, s.params_hash()) for s in snapshots}
    outcomes = list(strategy.iter_outcomes(snapshots))
    emitted = {(o.selection, _params_hash(o.params)) for o in outcomes}

    # Note: GOALS_BOTH_TEAMS normalises "GG" -> "YES" / "NG" -> "NO";
    # our seed already uses the canonical labels so the mapping is
    # identity. Any new strategy that canonicalises selections should
    # either seed the canonical label or extend this test to account
    # for the mapping.
    missing = expected - emitted
    assert not missing, f"iter_outcomes dropped seeded selections for {market.value}: {missing}"


@pytest.mark.parametrize("market", registered_markets(), ids=lambda m: m.value)
def test_iter_outcomes_dedupes_repeats(market: Market) -> None:
    """Feeding the seed twice must not produce duplicate outcomes."""
    strategy = strategy_for(market)
    snapshots = _seed_odds_for_market(market) * 2
    outcomes = list(strategy.iter_outcomes(snapshots))
    keys = [(o.selection, _params_hash(o.params)) for o in outcomes]
    assert len(keys) == len(set(keys)), f"duplicate outcomes emitted for {market.value}: {keys}"


@pytest.mark.parametrize("market", registered_markets(), ids=lambda m: m.value)
def test_compute_probability_returns_nonzero_on_hand_sample(market: Market) -> None:
    """At least one outcome must return ``0 < p <= 1`` on the hand sample."""
    strategy = strategy_for(market)
    snapshots = _seed_odds_for_market(market)
    outcomes = list(strategy.iter_outcomes(snapshots))

    probs: dict[str, float] = {}
    for outcome in outcomes:
        p = strategy.compute_probability(
            outcome,
            values_home=list(SAMPLE_HOME),
            values_away=list(SAMPLE_AWAY),
        )
        assert 0.0 <= p <= 1.0, f"{market.value}/{outcome.selection}: probability {p} not in [0,1]"
        probs[f"{outcome.selection}|{_params_hash(outcome.params)}"] = p

    assert any(p > 0.0 for p in probs.values()), (
        f"every outcome for {market.value} priced at zero on the hand sample: {probs}"
    )


@pytest.mark.parametrize("market", registered_markets(), ids=lambda m: m.value)
def test_compute_probability_is_empty_safe(market: Market) -> None:
    """Empty neighbour samples must produce ``0.0``, never raise."""
    strategy = strategy_for(market)
    snapshots = _seed_odds_for_market(market)
    for outcome in strategy.iter_outcomes(snapshots):
        p = strategy.compute_probability(outcome, values_home=[], values_away=[])
        assert p == 0.0


@pytest.mark.parametrize("market", registered_markets(), ids=lambda m: m.value)
def test_validate_result_returns_none_on_missing_inputs(market: Market) -> None:
    """``validate_result`` returns ``None`` when both realized values are missing.

    Per-team markets (``corner_team``, ``goals_team``) legitimately
    decide on one side alone; we therefore only assert the universally
    true both-sides-missing case here.
    """
    strategy = strategy_for(market)
    snapshots = _seed_odds_for_market(market)
    outcomes = list(strategy.iter_outcomes(snapshots))
    assert outcomes, f"no outcomes emitted for {market.value}"
    sample = outcomes[0]
    assert strategy.validate_result(sample, home_value=None, away_value=None) is None


def test_goals_both_teams_canonicalises_gg_ng() -> None:
    """``YES``/``GG``/``NO``/``NG`` fold to the canonical ``YES``/``NO`` labels.

    This is the one strategy that rewrites selections; covered here to
    guard against a silent loss of the mapping.
    """
    strategy = strategy_for(Market.GOALS_BOTH_TEAMS)
    snapshots = [
        _snap(Market.GOALS_BOTH_TEAMS, "GG", {}, 1.75),
        _snap(Market.GOALS_BOTH_TEAMS, "NG", {}, 2.05),
        _snap(Market.GOALS_BOTH_TEAMS, "YES", {}, 1.80),
        _snap(Market.GOALS_BOTH_TEAMS, "NO", {}, 2.00),
    ]
    outcomes = list(strategy.iter_outcomes(snapshots))
    selections = sorted(o.selection for o in outcomes)
    assert selections == ["NO", "YES"]
