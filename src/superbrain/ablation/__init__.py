"""Automated feature-subset search for the value-bet engine.

This package is the only approved feature-selection path for the
engine. It exists because the engine is bet-agnostic — every bet
strategy nominates its ``target_stat_columns`` independently — which
means the right clustering *feature* set is a function of the bet
being priced, the league, and the slice of history under analysis.
Picking those by hand is out of scope per ``docs/brief.md``.

See :class:`FeatureAblationStudy` for the entry point and
:mod:`superbrain.ablation.persistence` for the parquet contract shared
with the API / frontend (read-only via DuckDB).
"""

from __future__ import annotations

from superbrain.ablation.persistence import (
    ABLATION_FRAME_SCHEMA,
    AblationRunRecord,
    read_ablation_runs,
    write_ablation_run,
)
from superbrain.ablation.study import (
    AblationOutcome,
    AblationResult,
    FeatureAblationStudy,
)

__all__ = [
    "ABLATION_FRAME_SCHEMA",
    "AblationOutcome",
    "AblationResult",
    "AblationRunRecord",
    "FeatureAblationStudy",
    "read_ablation_runs",
    "write_ablation_run",
]
