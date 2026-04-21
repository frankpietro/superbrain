"""Regenerate the engine golden regression corpus.

Seeds a deterministic synthetic lake, runs the value-bet pipeline end-to-end on
a held-out fixture across every market that the synthetic lake populates, and
serialises the pipeline output to a stable JSON structure under
``tests/engine/fixtures/golden/``.

Purpose: the regression test (``tests/engine/test_regression.py``) re-runs the
pipeline with the identical seed and asserts the output has not drifted from
the frozen snapshot. Any intentional algorithmic change must rerun this script
and commit the refreshed golden alongside the change.

Design choices:

- Uses the same fixture shape as ``tests/engine/test_pipeline.py``'s
  ``twenty_match_lake``: 20 training matches over 6 teams, plus one held-out
  upcoming fixture. That recipe is already proven to fire every market in the
  registry on the synthetic lake.
- Hash-based equality for the cluster partition (after canonical relabelling
  so cluster-id permutations don't trip the test) and the similarity matrix
  (SHA-256 of the key-sorted float64 matrix, rounded to 12 decimal places).
- Per-priced-outcome floats are rounded to 12 decimal places before hashing and
  JSON emission, accommodating bit-level BLAS/SciPy drift while still catching
  semantically meaningful regressions.
- ``ProbabilityConfig(quantile=0.5, min_matches=3)`` and ``n_clusters=3``
  match the pipeline test's ``PIPELINE_CONFIG``.

Usage::

    uv run python scripts/generate_engine_golden.py
"""

from __future__ import annotations

import hashlib
import json
import random
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from superbrain.core.markets import Market
from superbrain.core.models import (
    Bookmaker,
    IngestProvenance,
    League,
    Match,
    OddsSnapshot,
    TeamMatchStats,
    compute_match_id,
)
from superbrain.data.connection import Lake
from superbrain.engine.pipeline import (
    DEFAULT_FEATURE_COLUMNS,
    PricingConfig,
    build_engine_context,
    find_value_bets,
    price_fixture,
)
from superbrain.engine.probability import ProbabilityConfig

SEASON = "2023-24"
LEAGUE = League.SERIE_A
TEAMS: tuple[str, ...] = (
    "Alpha",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
)
RNG_SEED = 7
MIN_HISTORY_MATCHES = 30

PIPELINE_PROBABILITY = ProbabilityConfig(quantile=0.5, min_matches=3)
PIPELINE_CONFIG = PricingConfig(
    n_clusters=3,
    feature_columns=DEFAULT_FEATURE_COLUMNS,
    probability=PIPELINE_PROBABILITY,
)

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "engine" / "fixtures" / "golden"
GOLDEN_FILE = GOLDEN_DIR / "engine_pipeline.json"


@dataclass(frozen=True)
class Corpus:
    """All the golden pieces we freeze for regression checks."""

    fixture: dict[str, Any]
    config: dict[str, Any]
    cluster_partition_checksum: str
    similarity_matrix_checksum: str
    priced_outcomes: list[dict[str, Any]]
    value_bets: list[dict[str, Any]]


def _pos(value: float) -> int:
    return max(0, round(value))


def build_lake_fixtures(
    rng_seed: int = RNG_SEED,
) -> tuple[list[Match], list[TeamMatchStats], Match]:
    """Return ``(matches, stats, upcoming_fixture)``.

    20 training fixtures generated from a round-robin over 6 teams; the 21st
    fixture is held out and used as the pricing target. Stats are fully
    deterministic from the seed.

    :param rng_seed: seed for the Random instance driving goals/stats sampling.
    :return: tuple of the training match list, the training stat list, and the
        held-out upcoming fixture.
    """
    rng = random.Random(rng_seed)
    ingested = datetime(2024, 6, 1, tzinfo=UTC)
    style_seed = {team: rng.gauss(0.0, 1.0) for team in TEAMS}

    pairs: list[tuple[str, str]] = []
    for i, home in enumerate(TEAMS):
        for away in TEAMS[i + 1 :]:
            pairs.append((home, away))
            pairs.append((away, home))
    training_pairs = pairs[:20]
    upcoming_pair = pairs[20]

    day0 = date(2023, 8, 1)
    matches: list[Match] = []
    stats: list[TeamMatchStats] = []

    for idx, (home, away) in enumerate(training_pairs):
        match_date = day0 + timedelta(days=idx * 3)
        home_goals = rng.randint(0, 4)
        away_goals = rng.randint(0, 3)
        mid = compute_match_id(home, away, match_date, LEAGUE)
        matches.append(
            Match(
                match_id=mid,
                league=LEAGUE,
                season=SEASON,
                match_date=match_date,
                home_team=home,
                away_team=away,
                home_goals=home_goals,
                away_goals=away_goals,
                source="golden",
                ingested_at=ingested,
            )
        )
        for team, opp, is_home, goals in (
            (home, away, True, home_goals),
            (away, home, False, away_goals),
        ):
            bias = style_seed[team] - style_seed[opp]
            stats.append(
                TeamMatchStats(
                    match_id=mid,
                    team=team,
                    is_home=is_home,
                    league=LEAGUE,
                    season=SEASON,
                    match_date=match_date,
                    goals=int(goals),
                    goals_conceded=(away_goals if is_home else home_goals),
                    shots=_pos(12 + 2 * bias + rng.gauss(0, 2)),
                    shots_on_target=_pos(5 + bias + rng.gauss(0, 1.2)),
                    corners=_pos(5 + bias + rng.gauss(0, 1.6)),
                    yellow_cards=_pos(2 + rng.gauss(0, 1)),
                    fouls=_pos(11 + rng.gauss(0, 2)),
                    red_cards=0,
                    source="golden",
                    ingested_at=ingested,
                )
            )

    upcoming_home, upcoming_away = upcoming_pair
    upcoming_date = day0 + timedelta(days=len(training_pairs) * 3 + 3)
    upcoming_mid = compute_match_id(upcoming_home, upcoming_away, upcoming_date, LEAGUE)
    upcoming = Match(
        match_id=upcoming_mid,
        league=LEAGUE,
        season=SEASON,
        match_date=upcoming_date,
        home_team=upcoming_home,
        away_team=upcoming_away,
        source="golden",
        ingested_at=ingested,
    )
    return matches, stats, upcoming


def build_odds_for_fixture(fixture: Match) -> list[OddsSnapshot]:
    """Deterministic odds across the canonical 4 markets for ``fixture``."""
    base: dict[str, Any] = {
        "bookmaker": Bookmaker.SISAL,
        "bookmaker_event_id": f"evt-{fixture.match_id}",
        "match_id": fixture.match_id,
        "match_label": f"{fixture.home_team}-{fixture.away_team}",
        "match_date": fixture.match_date,
        "season": fixture.season,
        "league": fixture.league,
        "home_team": fixture.home_team,
        "away_team": fixture.away_team,
        "captured_at": datetime.combine(fixture.match_date, datetime.min.time(), tzinfo=UTC)
        - timedelta(hours=4),
        "source": "golden",
        "run_id": "golden",
    }
    out: list[OddsSnapshot] = []
    for sel, payout in (("OVER", 1.85), ("UNDER", 1.95)):
        out.append(
            OddsSnapshot(
                market=Market.GOALS_OVER_UNDER,
                market_params={"threshold": 2.5},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    for sel, payout in (("OVER", 1.80), ("UNDER", 2.00)):
        out.append(
            OddsSnapshot(
                market=Market.CORNER_TOTAL,
                market_params={"threshold": 9.5},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    for sel, payout in (("1", 2.20), ("X", 3.20), ("2", 3.00)):
        out.append(
            OddsSnapshot(
                market=Market.MATCH_1X2,
                market_params={},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    for sel, payout in (("YES", 1.75), ("NO", 2.05)):
        out.append(
            OddsSnapshot(
                market=Market.GOALS_BOTH_TEAMS,
                market_params={},
                selection=sel,
                payout=payout,
                **base,
            )
        )
    return out


def canonicalise_cluster_partition(team_to_cluster: dict[str, int]) -> list[list[str]]:
    """Group teams by cluster id, sort alphabetically, sort groups by first member.

    Produces a nested list that is invariant under any cluster-id relabelling
    which preserves the partition.
    """
    grouped: dict[int, list[str]] = {}
    for team, cid in team_to_cluster.items():
        grouped.setdefault(cid, []).append(team)
    groups = [sorted(members) for members in grouped.values()]
    groups.sort(key=lambda g: g[0])
    return groups


def hash_object(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def hash_similarity_matrix(sim_values: np.ndarray, keys: list[tuple[str, str]]) -> str:
    order = sorted(range(len(keys)), key=lambda i: keys[i])
    reordered = sim_values[np.ix_(order, order)].astype(np.float64)
    reordered = np.round(reordered, 12)
    return hashlib.sha256(reordered.tobytes()).hexdigest()


def build_corpus(tmp_root: Path) -> Corpus:
    matches, stats, upcoming = build_lake_fixtures()
    if len(matches) != 20:
        raise RuntimeError(f"expected 20 training matches, got {len(matches)}")

    lake = Lake(root=tmp_root / "lake")
    lake.ensure_schema()
    provenance = IngestProvenance(
        source="golden",
        run_id="golden",
        actor="golden",
        captured_at=datetime(2024, 6, 1, tzinfo=UTC),
    )
    lake.ingest_matches(matches, provenance=provenance)
    lake.ingest_team_match_stats(stats, provenance=provenance)

    snapshots = build_odds_for_fixture(upcoming)
    lake.ingest_odds(snapshots, provenance=provenance)

    ctx = build_engine_context(
        lake,
        fixture=upcoming,
        config=PIPELINE_CONFIG,
        min_history_matches=MIN_HISTORY_MATCHES,
    )
    if ctx is None:
        raise RuntimeError("synthetic lake produced no engine context; corpus would be empty")

    partition = canonicalise_cluster_partition(ctx.assignment.team_to_cluster)
    cluster_checksum = hash_object(partition)

    sim_matrix = ctx.similarity.matrix
    sim_keys = ctx.similarity.keys
    if sim_matrix.size > 0:
        similarity_checksum = hash_similarity_matrix(sim_matrix, sim_keys)
    else:
        similarity_checksum = hash_object([])

    priced = price_fixture(
        lake,
        fixture=upcoming,
        odds_snapshots=snapshots,
        config=PIPELINE_CONFIG,
        min_history_matches=MIN_HISTORY_MATCHES,
        context=ctx,
    )
    priced_entries = [
        {
            "market": p.outcome.market.value,
            "selection": p.outcome.selection,
            "params": p.outcome.params,
            "target_columns": p.target_columns,
            "sample_size": p.sample_size,
            "model_probability": round(p.model_probability, 12),
            "model_payout": round(p.model_payout, 12),
        }
        for p in priced
    ]
    priced_entries.sort(
        key=lambda e: (
            e["market"],
            e["selection"],
            json.dumps(e["params"], sort_keys=True),
        )
    )

    value_bets = find_value_bets(
        lake,
        fixture=upcoming,
        edge_threshold=0.0,
        odds_snapshots=snapshots,
        config=PIPELINE_CONFIG,
        context=ctx,
    )
    value_entries = [
        {
            "bookmaker": vb.bookmaker,
            "market": vb.priced.outcome.market.value,
            "selection": vb.priced.outcome.selection,
            "params": vb.priced.outcome.params,
            "decimal_odds": round(vb.decimal_odds, 12),
            "book_probability": round(vb.book_probability, 12),
            "model_probability": round(vb.priced.model_probability, 12),
            "edge": round(vb.edge, 12),
        }
        for vb in value_bets
    ]
    value_entries.sort(
        key=lambda e: (
            e["market"],
            e["selection"],
            e["bookmaker"],
            json.dumps(e["params"], sort_keys=True),
        )
    )

    return Corpus(
        fixture={
            "match_id": upcoming.match_id,
            "home_team": upcoming.home_team,
            "away_team": upcoming.away_team,
            "match_date": upcoming.match_date.isoformat(),
            "season": upcoming.season,
            "league": upcoming.league.value,
        },
        config={
            "n_clusters": PIPELINE_CONFIG.n_clusters,
            "feature_columns": list(PIPELINE_CONFIG.feature_columns),
            "quantile": PIPELINE_CONFIG.probability.quantile,
            "min_matches": PIPELINE_CONFIG.probability.min_matches,
            "edge_threshold": 0.0,
            "rng_seed": RNG_SEED,
            "min_history_matches": MIN_HISTORY_MATCHES,
        },
        cluster_partition_checksum=cluster_checksum,
        similarity_matrix_checksum=similarity_checksum,
        priced_outcomes=priced_entries,
        value_bets=value_entries,
    )


def write_corpus(corpus: Corpus, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fixture": corpus.fixture,
        "config": corpus.config,
        "cluster_partition_checksum": corpus.cluster_partition_checksum,
        "similarity_matrix_checksum": corpus.similarity_matrix_checksum,
        "priced_outcomes": corpus.priced_outcomes,
        "value_bets": corpus.value_bets,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        corpus = build_corpus(Path(tmp))
        write_corpus(corpus, GOLDEN_FILE)
        print(f"wrote {GOLDEN_FILE.relative_to(GOLDEN_FILE.parent.parent.parent.parent)}")
        print(f"  priced_outcomes: {len(corpus.priced_outcomes)}")
        print(f"  value_bets:      {len(corpus.value_bets)}")
        print(f"  cluster hash:    {corpus.cluster_partition_checksum[:16]}...")
        print(f"  similarity hash: {corpus.similarity_matrix_checksum[:16]}...")


if __name__ == "__main__":
    main()
