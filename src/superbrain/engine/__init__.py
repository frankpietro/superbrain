"""Value-bet engine: clustering, similarity, probability, and the bet-agnostic registry.

The algorithm is the product. Phase 4a locks the old ``refactored_src``
behaviour under a golden regression corpus; improvements in phase 4b
must keep it green. See ``docs/knowledge.md`` → *Algorithm correctness
contract* and *Value-bet engine (phase 4a)*.
"""

from superbrain.engine.backtest import (
    BacktestBet,
    BacktestReport,
    iter_fixtures_from_lake,
    run_backtest,
)
from superbrain.engine.bets import (
    BET_REGISTRY,
    BetStrategy,
    EngineContext,
    Outcome,
    register,
    registered_markets,
    strategy_for,
)
from superbrain.engine.clustering import (
    CLUSTER_COL,
    OPPONENT_CLUSTER_COL,
    OPPONENT_COL,
    ClusterAssignment,
    cluster_teams,
    merge_opponent_clusters,
    prepare_team_match_stats,
)
from superbrain.engine.pipeline import (
    DEFAULT_EDGE_THRESHOLD,
    DEFAULT_FEATURE_COLUMNS,
    DEFAULT_MIN_HISTORY_MATCHES,
    DEFAULT_N_CLUSTERS,
    PricedOutcome,
    PricingConfig,
    ValueBet,
    build_engine_context,
    find_value_bets,
    price_fixture,
    season_for_date,
)
from superbrain.engine.probability import (
    DEFAULT_MIN_MATCHES,
    DEFAULT_QUANTILE,
    ProbabilityConfig,
    TargetStatIndex,
    collect_neighbor_values,
)
from superbrain.engine.similarity import (
    SimilarityMatrix,
    build_similarity_matrix,
    find_similar_team_seasons,
    frobenius_similarity,
    similarity_threshold,
)

__all__ = [
    "BET_REGISTRY",
    "CLUSTER_COL",
    "DEFAULT_EDGE_THRESHOLD",
    "DEFAULT_FEATURE_COLUMNS",
    "DEFAULT_MIN_HISTORY_MATCHES",
    "DEFAULT_MIN_MATCHES",
    "DEFAULT_N_CLUSTERS",
    "DEFAULT_QUANTILE",
    "OPPONENT_CLUSTER_COL",
    "OPPONENT_COL",
    "BacktestBet",
    "BacktestReport",
    "BetStrategy",
    "ClusterAssignment",
    "EngineContext",
    "Outcome",
    "PricedOutcome",
    "PricingConfig",
    "ProbabilityConfig",
    "SimilarityMatrix",
    "TargetStatIndex",
    "ValueBet",
    "build_engine_context",
    "build_similarity_matrix",
    "cluster_teams",
    "collect_neighbor_values",
    "find_similar_team_seasons",
    "find_value_bets",
    "frobenius_similarity",
    "iter_fixtures_from_lake",
    "merge_opponent_clusters",
    "prepare_team_match_stats",
    "price_fixture",
    "register",
    "registered_markets",
    "run_backtest",
    "season_for_date",
    "similarity_threshold",
    "strategy_for",
]
