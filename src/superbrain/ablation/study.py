"""Feature-subset search over the clustering inputs.

The engine clusters team-match vectors on a fixed tuple of
``TeamMatchStats`` columns (``PricingConfig.feature_columns``).
Picking those columns is a modelling decision — the right set depends
on the bet being priced, the league, and the slice of history under
analysis. :class:`FeatureAblationStudy` automates that decision by
wrapping :func:`superbrain.engine.backtest.run_backtest` in a search
loop.

Phase 4b ships the simplest loop we trust: **greedy forward
selection**. Extension hooks for beam-search and genetic variants are
called out in the class docstring and in the queued outbox entry.

The study is deterministic by construction: given identical inputs
(lake, fixtures, feature universe, tie-breaker order, and pricing
config) the best subset and the full trajectory of evaluated subsets
are reproducible bit-for-bit. The ``seed`` argument is reserved for
future stochastic search variants; greedy search does not consume it
but the test suite asserts that identical seeds + inputs imply
identical output parquet contents.
"""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from superbrain.ablation.persistence import (
    AblationRunRecord,
    write_ablation_run,
)
from superbrain.core.markets import Market
from superbrain.core.models import Match
from superbrain.data.connection import Lake
from superbrain.engine.backtest import (
    BacktestReport,
    OddsProvider,
    run_backtest,
)
from superbrain.engine.pipeline import (
    DEFAULT_EDGE_THRESHOLD,
    DEFAULT_MIN_HISTORY_MATCHES,
    PricingConfig,
)

logger = logging.getLogger(__name__)

MIN_SUBSET_SIZE: Final = 2
"""Clustering in cosine / average-linkage is ill-defined with a single
column — we refuse subsets smaller than this."""


@dataclass(frozen=True)
class AblationOutcome:
    """Result of evaluating one feature subset.

    :ivar feature_subset: the subset evaluated.
    :ivar report: the full :class:`BacktestReport` for the subset.
    :ivar started_at: UTC start of this trial.
    :ivar finished_at: UTC end of this trial.
    """

    feature_subset: tuple[str, ...]
    report: BacktestReport
    started_at: datetime
    finished_at: datetime

    @property
    def roi(self) -> float:
        return float(self.report.roi)

    @property
    def hit_rate(self) -> float:
        return float(self.report.hit_rate)

    @property
    def n_matches(self) -> int:
        return int(self.report.n_bets)

    @property
    def avg_edge(self) -> float:
        bets = self.report.bets
        if not bets:
            return 0.0
        return sum(b.value_bet.edge for b in bets) / len(bets)


@dataclass(frozen=True)
class AblationResult:
    """Aggregate result of a :class:`FeatureAblationStudy` run.

    :ivar run_id: unique identifier for the run.
    :ivar bet_code: ``Market.value`` under study.
    :ivar trajectory: every evaluated subset, in the order they were tried.
    :ivar best: subset with the highest ROI in ``trajectory`` (ties broken
        by fewer features, then alphabetical subset).
    :ivar parquet_path: path to the persisted parquet (``None`` when the
        study was run with ``persist=False``).
    """

    run_id: str
    bet_code: str
    trajectory: tuple[AblationOutcome, ...]
    best: AblationOutcome
    parquet_path: Path | None = None


@dataclass
class FeatureAblationStudy:
    """Greedy forward-selection search over clustering features.

    Algorithm:

    1. Start from an empty selected set and a pool equal to the feature
       universe.
    2. At each step, evaluate the candidate subset ``selected + {f}`` for
       every ``f`` still in the pool. Evaluation means: run
       :func:`~superbrain.engine.backtest.run_backtest` with a
       :class:`PricingConfig` that overrides ``feature_columns`` with the
       candidate subset.
    3. Adopt the candidate with the highest ROI. Ties are broken by
       lexicographic order of the added feature -- this keeps the
       trajectory deterministic.
    4. Stop when no remaining feature improves ROI over the current best,
       or when the selected set equals the universe.

    Extension points for future phases:

    * Replace the greedy step with a beam search (keep the top ``k``
      partial subsets at every step) -- swap :meth:`_greedy_select` for a
      beam-aware variant.
    * Swap the search loop for a genetic algorithm -- override
      :meth:`_search` and return the trajectory plus best outcome. The
      ``seed`` argument already threads through; plug it into your RNG.

    :ivar lake: lake handle feeding the backtest.
    :ivar bet: ``Market`` the study evaluates against.
    :ivar feature_universe: pool of ``TeamMatchStats`` columns to search.
    :ivar fixtures: fixtures walked by each backtest trial.
    :ivar min_history_matches: floor gate on historical stats during pricing.
    :ivar edge_threshold: minimum edge per placed bet.
    :ivar stake: flat stake per placed bet.
    :ivar base_config: :class:`PricingConfig` cloned per trial; its
        ``feature_columns`` is overridden with the candidate subset.
    :ivar odds_provider: optional :class:`OddsProvider` used during backtests.
    :ivar tie_breaker: callable that orders candidates at each step. Defaults
        to alphabetical. Overriding it must return a stable permutation
        across runs to preserve determinism.
    :ivar seed: reserved for stochastic variants; unused by greedy search.
    """

    lake: Lake
    bet: Market
    feature_universe: Sequence[str]
    fixtures: Sequence[Match]
    min_history_matches: int = DEFAULT_MIN_HISTORY_MATCHES
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD
    stake: float = 1.0
    base_config: PricingConfig = field(default_factory=PricingConfig)
    odds_provider: OddsProvider | None = None
    tie_breaker: Callable[[Iterable[str]], list[str]] = field(default=sorted)
    seed: int = 0

    def run(
        self,
        *,
        run_id: str | None = None,
        persist: bool = True,
        data_root: Path | None = None,
    ) -> AblationResult:
        """Execute the study and (optionally) persist the trajectory.

        :param run_id: stable identifier for this run; a UUID4 is
            generated when ``None``.
        :param persist: when ``True``, write the trajectory to
            ``<data_root>/ablation_runs/<bet>/<run_id>.parquet``.
        :param data_root: workspace data directory. Defaults to ``"data"``.
        :return: the :class:`AblationResult`.
        """
        universe = self._validated_universe()
        run_id = run_id or uuid.uuid4().hex
        trajectory = self._search(universe)
        best = self._pick_best(trajectory)

        parquet_path: Path | None = None
        if persist:
            records = [
                AblationRunRecord(
                    run_id=run_id,
                    bet_code=self.bet.value,
                    feature_subset=outcome.feature_subset,
                    n_matches=outcome.n_matches,
                    roi=outcome.roi,
                    hit_rate=outcome.hit_rate,
                    avg_edge=outcome.avg_edge,
                    started_at=outcome.started_at,
                    finished_at=outcome.finished_at,
                )
                for outcome in trajectory
            ]
            parquet_path = write_ablation_run(records, root=data_root or Path("data"))

        return AblationResult(
            run_id=run_id,
            bet_code=self.bet.value,
            trajectory=tuple(trajectory),
            best=best,
            parquet_path=parquet_path,
        )

    def _validated_universe(self) -> list[str]:
        if len(self.feature_universe) < MIN_SUBSET_SIZE:
            raise ValueError(
                "FeatureAblationStudy requires a feature universe of at least "
                f"{MIN_SUBSET_SIZE} columns; got {list(self.feature_universe)}"
            )
        universe = list(dict.fromkeys(self.feature_universe))
        if len(universe) != len(self.feature_universe):
            logger.warning("feature_universe contains duplicates; dedup'd to %s", universe)
        return universe

    def _search(self, universe: list[str]) -> list[AblationOutcome]:
        """Greedy forward selection over ``universe``.

        Subclasses that swap the search strategy should return the full
        evaluation trajectory in the order trials were performed.
        """
        trajectory: list[AblationOutcome] = []
        selected: list[str] = []
        pool = list(self.tie_breaker(universe))

        seeded = self._greedy_seed(pool)
        trajectory.append(seeded)
        selected = list(seeded.feature_subset)
        pool = [f for f in pool if f not in seeded.feature_subset]

        current_best_roi = seeded.roi
        while pool:
            best_candidate: AblationOutcome | None = None
            for feature in self.tie_breaker(pool):
                candidate = (*selected, feature)
                outcome = self._evaluate(candidate)
                trajectory.append(outcome)
                if best_candidate is None or _roi_gt(outcome, best_candidate):
                    best_candidate = outcome
            if best_candidate is None or not _roi_gt_scalar(best_candidate.roi, current_best_roi):
                break
            added = next(f for f in best_candidate.feature_subset if f not in selected)
            selected = list(best_candidate.feature_subset)
            pool.remove(added)
            current_best_roi = best_candidate.roi
        return trajectory

    def _greedy_seed(self, ordered_universe: list[str]) -> AblationOutcome:
        """Seed the greedy search.

        We seed with all size-2 subsets that start with the first feature
        in ``tie_breaker`` order paired against every other feature. This
        keeps the first step cheap (N-1 backtests) while still honouring
        the ``MIN_SUBSET_SIZE`` floor on clustering inputs.
        """
        anchor = ordered_universe[0]
        best: AblationOutcome | None = None
        all_outcomes: list[AblationOutcome] = []
        for other in ordered_universe[1:]:
            subset = (anchor, other)
            outcome = self._evaluate(subset)
            all_outcomes.append(outcome)
            if best is None or _roi_gt(outcome, best):
                best = outcome
        assert best is not None
        logger.info(
            "ablation seed: best size-2 subset = %s (roi=%.4f)",
            best.feature_subset,
            best.roi,
        )
        return best

    def _evaluate(self, subset: tuple[str, ...]) -> AblationOutcome:
        """Run a single backtest for ``subset`` and return the outcome.

        Degenerate subsets (e.g. where every vector collapses to zero and
        cosine clustering refuses to run) are scored as an empty report
        rather than propagating the exception — the search continues and
        the trial is recorded with ROI=0, so the trajectory remains
        complete and auditable.
        """
        started = datetime.now(UTC)
        config = PricingConfig(
            n_clusters=self.base_config.n_clusters,
            feature_columns=subset,
            probability=self.base_config.probability,
        )
        try:
            report = run_backtest(
                self.lake,
                fixtures=list(self.fixtures),
                edge_threshold=self.edge_threshold,
                markets=[self.bet],
                config=config,
                min_history_matches=self.min_history_matches,
                stake=self.stake,
                odds_provider=self.odds_provider,
            )
        except ValueError as exc:
            logger.warning(
                "ablation: backtest failed for subset=%s (%s); scoring 0",
                subset,
                exc,
            )
            report = BacktestReport()
        finished = datetime.now(UTC)
        return AblationOutcome(
            feature_subset=subset,
            report=report,
            started_at=started,
            finished_at=finished,
        )

    @staticmethod
    def _pick_best(trajectory: Iterable[AblationOutcome]) -> AblationOutcome:
        """Return the best outcome with deterministic tie-breaking.

        Ranking: higher ROI wins; ties go to the smaller subset; further
        ties go to the lexicographically smaller subset.
        """
        best = None
        for outcome in trajectory:
            if best is None:
                best = outcome
                continue
            if _roi_gt(outcome, best):
                best = outcome
                continue
            if not math.isclose(outcome.roi, best.roi, rel_tol=0.0, abs_tol=1e-12):
                continue
            new_len = len(outcome.feature_subset)
            old_len = len(best.feature_subset)
            if new_len < old_len or (
                new_len == old_len and outcome.feature_subset < best.feature_subset
            ):
                best = outcome
        assert best is not None
        return best


def _roi_gt(a: AblationOutcome, b: AblationOutcome) -> bool:
    return _roi_gt_scalar(a.roi, b.roi)


def _roi_gt_scalar(a: float, b: float) -> bool:
    return (a - b) > 1e-12
