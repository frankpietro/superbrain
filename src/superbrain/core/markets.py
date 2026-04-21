"""Odds-market registry.

Every market is identified by a stable string code (``Market`` enum) and
carries metadata used by the engine (which statistic it resolves against),
by the scrapers (which bookmaker endpoint produces it), and by the analytics
layer (how to render it to humans).

The registry is deliberately open-closed: adding a market is adding a new
enum member plus a ``MARKET_METADATA`` entry, and downstream code that
switches on the enum picks up the default behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Market(StrEnum):
    CORNER_TOTAL = "corner_total"
    CORNER_TEAM = "corner_team"
    CORNER_1X2 = "corner_1x2"
    CORNER_COMBO = "corner_combo"
    CORNER_FIRST_TO = "corner_first_to"
    CORNER_HANDICAP = "corner_handicap"

    GOALS_OVER_UNDER = "goals_over_under"
    GOALS_BOTH_TEAMS = "goals_both_teams"
    GOALS_TEAM = "goals_team"
    GOALS_EXACT = "goals_exact"

    CARDS_TOTAL = "cards_total"
    CARDS_TEAM = "cards_team"

    MATCH_1X2 = "match_1x2"
    MATCH_DOUBLE_CHANCE = "match_double_chance"

    MULTIGOL = "multigol"
    MULTIGOL_TEAM = "multigol_team"

    SCORE_EXACT = "score_exact"
    SCORE_HT_FT = "score_ht_ft"

    SHOTS_TOTAL = "shots_total"
    SHOTS_ON_TARGET_TOTAL = "shots_on_target_total"

    COMBO_1X2_OVER_UNDER = "combo_1x2_over_under"
    COMBO_BTTS_OVER_UNDER = "combo_btts_over_under"

    HALVES_OVER_UNDER = "halves_over_under"


class MarketCategory(StrEnum):
    CORNERS = "corners"
    GOALS = "goals"
    CARDS = "cards"
    MATCH_RESULT = "match_result"
    SHOTS = "shots"
    COMBO = "combo"
    HALVES = "halves"


@dataclass(frozen=True)
class MarketMetadata:
    code: Market
    category: MarketCategory
    human_name: str
    param_keys: tuple[str, ...] = ()
    selections: tuple[str, ...] = ()
    target_stat: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


MARKET_METADATA: dict[Market, MarketMetadata] = {
    Market.CORNER_TOTAL: MarketMetadata(
        code=Market.CORNER_TOTAL,
        category=MarketCategory.CORNERS,
        human_name="Corners — total over/under",
        param_keys=("threshold",),
        selections=("OVER", "UNDER"),
        target_stat="corners_total",
    ),
    Market.CORNER_TEAM: MarketMetadata(
        code=Market.CORNER_TEAM,
        category=MarketCategory.CORNERS,
        human_name="Corners — team over/under",
        param_keys=("threshold", "team"),
        selections=("OVER", "UNDER"),
        target_stat="corners_team",
    ),
    Market.CORNER_1X2: MarketMetadata(
        code=Market.CORNER_1X2,
        category=MarketCategory.CORNERS,
        human_name="Corners — 1X2",
        param_keys=(),
        selections=("1", "X", "2"),
        target_stat="corners_diff",
    ),
    Market.CORNER_COMBO: MarketMetadata(
        code=Market.CORNER_COMBO,
        category=MarketCategory.CORNERS,
        human_name="Corners — combo (home/away thresholds)",
        param_keys=("threshold_1", "threshold_2"),
        selections=("OVER+OVER", "OVER+UNDER", "UNDER+OVER", "UNDER+UNDER"),
        target_stat="corners_home_away",
    ),
    Market.CORNER_FIRST_TO: MarketMetadata(
        code=Market.CORNER_FIRST_TO,
        category=MarketCategory.CORNERS,
        human_name="Corners — first to reach N",
        param_keys=("target_corners",),
        selections=("HOME", "AWAY", "NONE"),
        target_stat="corners_race",
    ),
    Market.CORNER_HANDICAP: MarketMetadata(
        code=Market.CORNER_HANDICAP,
        category=MarketCategory.CORNERS,
        human_name="Corners — handicap",
        param_keys=("handicap",),
        selections=("HOME", "AWAY"),
        target_stat="corners_diff",
    ),
    Market.GOALS_OVER_UNDER: MarketMetadata(
        code=Market.GOALS_OVER_UNDER,
        category=MarketCategory.GOALS,
        human_name="Goals — total over/under",
        param_keys=("threshold",),
        selections=("OVER", "UNDER"),
        target_stat="goals_total",
    ),
    Market.GOALS_BOTH_TEAMS: MarketMetadata(
        code=Market.GOALS_BOTH_TEAMS,
        category=MarketCategory.GOALS,
        human_name="Both teams to score",
        selections=("YES", "NO"),
        target_stat="btts",
    ),
    Market.GOALS_TEAM: MarketMetadata(
        code=Market.GOALS_TEAM,
        category=MarketCategory.GOALS,
        human_name="Goals — team over/under",
        param_keys=("team", "threshold"),
        selections=("OVER", "UNDER"),
        target_stat="goals_team",
    ),
    Market.GOALS_EXACT: MarketMetadata(
        code=Market.GOALS_EXACT,
        category=MarketCategory.GOALS,
        human_name="Goals — exact total",
        param_keys=("exact",),
        target_stat="goals_total",
    ),
    Market.CARDS_TOTAL: MarketMetadata(
        code=Market.CARDS_TOTAL,
        category=MarketCategory.CARDS,
        human_name="Cards — total over/under",
        param_keys=("threshold",),
        selections=("OVER", "UNDER"),
        target_stat="cards_total",
    ),
    Market.CARDS_TEAM: MarketMetadata(
        code=Market.CARDS_TEAM,
        category=MarketCategory.CARDS,
        human_name="Cards — team over/under",
        param_keys=("threshold", "team"),
        selections=("OVER", "UNDER"),
        target_stat="cards_team",
    ),
    Market.MATCH_1X2: MarketMetadata(
        code=Market.MATCH_1X2,
        category=MarketCategory.MATCH_RESULT,
        human_name="Match result (1X2)",
        selections=("1", "X", "2"),
        target_stat="goals_diff",
    ),
    Market.MATCH_DOUBLE_CHANCE: MarketMetadata(
        code=Market.MATCH_DOUBLE_CHANCE,
        category=MarketCategory.MATCH_RESULT,
        human_name="Double chance",
        selections=("1X", "12", "X2"),
        target_stat="goals_diff",
    ),
    Market.MULTIGOL: MarketMetadata(
        code=Market.MULTIGOL,
        category=MarketCategory.GOALS,
        human_name="Multigol",
        param_keys=("lower", "upper"),
        target_stat="goals_total",
    ),
    Market.MULTIGOL_TEAM: MarketMetadata(
        code=Market.MULTIGOL_TEAM,
        category=MarketCategory.GOALS,
        human_name="Multigol — team",
        param_keys=("team", "lower", "upper"),
        target_stat="goals_team",
    ),
    Market.SCORE_EXACT: MarketMetadata(
        code=Market.SCORE_EXACT,
        category=MarketCategory.MATCH_RESULT,
        human_name="Exact score",
        param_keys=("home", "away"),
        target_stat="score_exact",
    ),
    Market.SCORE_HT_FT: MarketMetadata(
        code=Market.SCORE_HT_FT,
        category=MarketCategory.MATCH_RESULT,
        human_name="Half-time / full-time",
        param_keys=("ht", "ft"),
        target_stat="score_ht_ft",
    ),
    Market.SHOTS_TOTAL: MarketMetadata(
        code=Market.SHOTS_TOTAL,
        category=MarketCategory.SHOTS,
        human_name="Shots — total over/under",
        param_keys=("threshold",),
        selections=("OVER", "UNDER"),
        target_stat="shots_total",
    ),
    Market.SHOTS_ON_TARGET_TOTAL: MarketMetadata(
        code=Market.SHOTS_ON_TARGET_TOTAL,
        category=MarketCategory.SHOTS,
        human_name="Shots on target — total over/under",
        param_keys=("threshold",),
        selections=("OVER", "UNDER"),
        target_stat="shots_on_target_total",
    ),
    Market.COMBO_1X2_OVER_UNDER: MarketMetadata(
        code=Market.COMBO_1X2_OVER_UNDER,
        category=MarketCategory.COMBO,
        human_name="Combo — 1X2 + goals over/under",
        param_keys=("result_1x2", "threshold"),
        selections=("OVER", "UNDER"),
        target_stat="combo_1x2_goals",
    ),
    Market.COMBO_BTTS_OVER_UNDER: MarketMetadata(
        code=Market.COMBO_BTTS_OVER_UNDER,
        category=MarketCategory.COMBO,
        human_name="Combo — BTTS + goals over/under",
        param_keys=("bet_btts", "threshold"),
        selections=("OVER", "UNDER"),
        target_stat="combo_btts_goals",
    ),
    Market.HALVES_OVER_UNDER: MarketMetadata(
        code=Market.HALVES_OVER_UNDER,
        category=MarketCategory.HALVES,
        human_name="Halves — goals over/under per half",
        param_keys=("half", "threshold"),
        selections=("OVER", "UNDER"),
        target_stat="goals_half",
    ),
}


def metadata_for(market: Market | str) -> MarketMetadata:
    """Return metadata for a market code, accepting the enum or its string.

    :param market: market code (enum or equivalent string)
    :return: the registered ``MarketMetadata`` for that market
    """
    key = Market(market) if not isinstance(market, Market) else market
    return MARKET_METADATA[key]
