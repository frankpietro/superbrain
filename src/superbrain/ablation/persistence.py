"""Persistence contract for ablation runs.

Each :class:`~superbrain.ablation.study.FeatureAblationStudy` run is
dumped to a parquet at ``<root>/ablation_runs/<bet_code>/<run_id>.parquet``.
One row is emitted per feature subset evaluated during the search so
the full search trajectory (greedy at phase 4b, extensible to genetic
/ beam-search later) can be reconstructed and inspected via DuckDB
from the API / SPA.

The schema is deliberately flat and string-serializable so DuckDB can
union-read across bets without surprises:

``run_id, bet_code, feature_subset, n_matches, roi, hit_rate,
avg_edge, started_at, finished_at``

``feature_subset`` is stored as a ``list[str]`` polars column (read by
DuckDB as a native list) — the SPA flattens it on display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final

import duckdb
import polars as pl

ABLATION_ROOT_NAME: Final = "ablation_runs"

ABLATION_FRAME_SCHEMA: Final[pl.Schema] = pl.Schema(
    [
        ("run_id", pl.String()),
        ("bet_code", pl.String()),
        ("feature_subset", pl.List(pl.String())),
        ("n_matches", pl.Int64()),
        ("roi", pl.Float64()),
        ("hit_rate", pl.Float64()),
        ("avg_edge", pl.Float64()),
        ("started_at", pl.Datetime(time_zone="UTC")),
        ("finished_at", pl.Datetime(time_zone="UTC")),
    ]
)


@dataclass(frozen=True)
class AblationRunRecord:
    """One evaluated feature subset within an ablation run.

    :ivar run_id: study-wide identifier (stable across rows in one run).
    :ivar bet_code: ``Market.value`` of the bet under study.
    :ivar feature_subset: stat columns fed to the clusterer for this trial.
    :ivar n_matches: fixtures evaluated in the trial's backtest.
    :ivar roi: flat-stake ROI of the trial (``total_profit / total_stake``).
    :ivar hit_rate: ``wins / (wins + losses)`` for the trial.
    :ivar avg_edge: mean absolute edge across the trial's placed bets.
    :ivar started_at: UTC wall-clock timestamp at the trial's start.
    :ivar finished_at: UTC wall-clock timestamp at the trial's end.
    """

    run_id: str
    bet_code: str
    feature_subset: tuple[str, ...]
    n_matches: int
    roi: float
    hit_rate: float
    avg_edge: float
    started_at: datetime
    finished_at: datetime

    def as_row(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "bet_code": self.bet_code,
            "feature_subset": list(self.feature_subset),
            "n_matches": self.n_matches,
            "roi": float(self.roi),
            "hit_rate": float(self.hit_rate),
            "avg_edge": float(self.avg_edge),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class AblationRoot:
    """Helper wrapping the on-disk layout of the ablation runs directory."""

    root: Path = field(default=Path("data"))

    @property
    def base(self) -> Path:
        return self.root / ABLATION_ROOT_NAME

    def bet_dir(self, bet_code: str) -> Path:
        return self.base / bet_code

    def run_path(self, *, bet_code: str, run_id: str) -> Path:
        return self.bet_dir(bet_code) / f"{run_id}.parquet"


def write_ablation_run(records: list[AblationRunRecord], *, root: Path) -> Path:
    """Dump ``records`` to ``<root>/ablation_runs/<bet>/<run_id>.parquet``.

    All records must share the same ``(run_id, bet_code)`` pair — a
    single parquet file corresponds to exactly one ablation run. Raises
    ``ValueError`` if the input is empty or inconsistent.

    :param records: one record per evaluated feature subset
    :param root: workspace data root (usually ``<repo>/data``)
    :return: the parquet path that was written
    """
    if not records:
        raise ValueError("write_ablation_run requires at least one record")
    run_ids = {r.run_id for r in records}
    bet_codes = {r.bet_code for r in records}
    if len(run_ids) != 1 or len(bet_codes) != 1:
        raise ValueError(
            "write_ablation_run: records must share (run_id, bet_code) — "
            f"got run_ids={run_ids}, bet_codes={bet_codes}"
        )
    bet_code = next(iter(bet_codes))
    run_id = next(iter(run_ids))

    layout = AblationRoot(root=root)
    layout.bet_dir(bet_code).mkdir(parents=True, exist_ok=True)
    frame = pl.DataFrame([r.as_row() for r in records], schema=ABLATION_FRAME_SCHEMA)
    target = layout.run_path(bet_code=bet_code, run_id=run_id)
    frame.write_parquet(target)
    return target


def read_ablation_runs(*, root: Path, bet_code: str | None = None) -> pl.DataFrame:
    """Read every ablation run into a single polars frame via DuckDB.

    DuckDB globs the parquet tree so the API can stream results without
    holding them all in memory. For the phase-4b volumes polars is
    equally fine; using DuckDB keeps the contract identical to the
    rest of the lake reads (``docs/knowledge.md`` → *Stack*).

    :param root: workspace data root
    :param bet_code: optional filter on the bet directory
    :return: union of all matching parquet files (empty frame if none)
    """
    layout = AblationRoot(root=root)
    if not layout.base.exists():
        return pl.DataFrame(schema=ABLATION_FRAME_SCHEMA)

    pattern = (
        layout.bet_dir(bet_code) / "*.parquet"
        if bet_code is not None
        else layout.base / "*" / "*.parquet"
    )
    files = sorted(layout.base.rglob("*.parquet"))
    if bet_code is not None:
        files = [p for p in files if p.parent.name == bet_code]
    if not files:
        return pl.DataFrame(schema=ABLATION_FRAME_SCHEMA)

    con = duckdb.connect(database=":memory:")
    try:
        arrow = con.execute(
            "SELECT * FROM read_parquet(?, union_by_name=true)",
            [str(pattern)],
        ).arrow()
    finally:
        con.close()
    return pl.from_arrow(arrow)  # type: ignore[return-value]
