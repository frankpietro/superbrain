"""Data-overview router: lake inventory for the SPA's *Data* tab.

``GET /data/overview`` walks every hive-partitioned table under the lake root,
counts rows per partition, exposes the column schema, and returns a handful
of stringified sample rows. Meant for a single cheap read — the endpoint
scans parquet footers for row counts and only materialises the first ``N``
rows of the sample frame.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import anyio
import polars as pl
from fastapi import APIRouter, Depends

from superbrain.api.deps import get_lake
from superbrain.api.schemas import (
    DataColumn,
    DataOverviewResponse,
    DataPartition,
    DataTableOverview,
)
from superbrain.data.connection import Lake

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data", tags=["data"])

_SAMPLE_ROWS = 5
_MAX_PARTITIONS = 500
# Order the cards intentionally: richest tables first.
_TABLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("matches", "matches_root", ("league", "season")),
    ("team_match_stats", "team_match_stats_root", ("league", "season")),
    ("odds", "odds_root", ("bookmaker", "market", "season")),
    ("team_elo", "team_elo_root", ("year_month",)),
    ("scrape_runs", "scrape_runs_root", ("bookmaker", "year_month")),
    ("simulation_runs", "simulation_runs_root", ("created_date",)),
)


@router.get("/overview", response_model=DataOverviewResponse)
async def overview(
    lake: Annotated[Lake, Depends(get_lake)],
) -> DataOverviewResponse:
    """Return a per-table inventory of the lake: counts, columns, samples."""
    return await anyio.to_thread.run_sync(_overview_sync, lake)


def _overview_sync(lake: Lake) -> DataOverviewResponse:
    tables: list[DataTableOverview] = []
    for name, attr, partition_keys in _TABLES:
        root: Path = getattr(lake.layout, attr)
        tables.append(_table_overview(name, root, partition_keys))
    return DataOverviewResponse(
        generated_at=datetime.now(UTC),
        lake_root=str(lake.root),
        tables=tables,
    )


def _table_overview(name: str, root: Path, partition_keys: tuple[str, ...]) -> DataTableOverview:
    if not root.exists():
        return DataTableOverview(
            name=name,
            root=str(root),
            partition_keys=list(partition_keys),
            exists=False,
            total_rows=0,
            columns=[],
            partitions=[],
            samples=[],
        )

    files = sorted(f for f in root.rglob("*.parquet") if f.name != "match_index.parquet")
    if not files:
        return DataTableOverview(
            name=name,
            root=str(root),
            partition_keys=list(partition_keys),
            exists=True,
            total_rows=0,
            columns=[],
            partitions=[],
            samples=[],
        )

    # Row counts are pulled from parquet footers without reading data.
    partition_rows: dict[tuple[str, ...], int] = {}
    total = 0
    for f in files:
        try:
            n = pl.scan_parquet(f).select(pl.len()).collect().item()
        except (pl.exceptions.ComputeError, OSError) as exc:  # pragma: no cover - defensive
            logger.warning("data/overview: failed to read %s (%s)", f, exc)
            continue
        total += int(n)
        key = _partition_tuple(f, root, partition_keys)
        partition_rows[key] = partition_rows.get(key, 0) + int(n)

    partitions = [
        DataPartition(
            values=dict(zip(partition_keys, key, strict=True)),
            rows=rows,
        )
        for key, rows in sorted(partition_rows.items(), key=lambda kv: (-kv[1], kv[0]))
    ][:_MAX_PARTITIONS]

    # Schema + samples: read the smallest file in full, or just its head.
    columns, samples = _schema_and_samples(files)

    return DataTableOverview(
        name=name,
        root=str(root),
        partition_keys=list(partition_keys),
        exists=True,
        total_rows=total,
        columns=columns,
        partitions=partitions,
        samples=samples,
    )


def _partition_tuple(file: Path, root: Path, partition_keys: tuple[str, ...]) -> tuple[str, ...]:
    """Extract the hive partition values for ``file`` in the order of ``partition_keys``.

    Missing keys (e.g. hand-placed file without a partition dir) fall through
    as ``""`` so the caller can still bucket them.
    """
    rel = file.relative_to(root).parts[:-1]
    parsed: dict[str, str] = {}
    for part in rel:
        if "=" in part:
            k, _, v = part.partition("=")
            parsed[k] = v
    return tuple(parsed.get(k, "") for k in partition_keys)


def _schema_and_samples(
    files: list[Path],
) -> tuple[list[DataColumn], list[dict[str, Any]]]:
    """Load the head of the smallest file and derive columns + samples."""
    smallest = min(files, key=lambda p: p.stat().st_size)
    try:
        head = pl.read_parquet(smallest).head(_SAMPLE_ROWS)
    except (pl.exceptions.ComputeError, OSError) as exc:  # pragma: no cover - defensive
        logger.warning("data/overview: failed to sample %s (%s)", smallest, exc)
        return [], []
    columns = [
        DataColumn(name=n, dtype=str(t)) for n, t in zip(head.columns, head.dtypes, strict=True)
    ]
    samples = [_stringify_row(row) for row in head.iter_rows(named=True)]
    return columns, samples


def _stringify_row(row: dict[str, Any]) -> dict[str, str | None]:
    """Cast every cell to a JSON-safe string; preserve ``None``."""
    out: dict[str, str | None] = {}
    for k, v in row.items():
        if v is None:
            out[k] = None
        elif isinstance(v, (dict, list, tuple)):
            out[k] = str(v)
        else:
            out[k] = str(v)
    return out
