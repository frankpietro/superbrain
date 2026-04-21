"""High-level interface to the DuckDB + Parquet data lake.

The :class:`Lake` class is the only type code outside this package should
touch. It hides the partition layout, the DuckDB session, and the schema
manifest behind a small, auditable API:

* :meth:`Lake.ensure_schema` — materialize directories and run migrations.
* :meth:`Lake.connect` — lazy DuckDB connection bound to this lake.
* :meth:`Lake.ingest_odds`, :meth:`Lake.ingest_matches`,
  :meth:`Lake.ingest_team_match_stats` — validated, dedupe-aware writes
  that always return an :class:`IngestReport`.
* :meth:`Lake.read_odds`, :meth:`Lake.read_matches` — union-by-name reads
  across partitions.
* :meth:`Lake.log_scrape_run` — append one audit row per scheduled run.

The implementation avoids global state. Tests and ephemeral jobs construct
their own :class:`Lake` pointed at a temporary root; the long-running API
server keeps exactly one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from superbrain.core.models import (
    IngestProvenance,
    IngestReport,
    Match,
    OddsSnapshot,
    ScrapeRun,
    TeamElo,
    TeamMatchStats,
)
from superbrain.data.migrations import MIGRATIONS
from superbrain.data.paths import LakeLayout, timestamped_filename
from superbrain.data.schemas import (
    MATCH_SCHEMA,
    ODDS_SCHEMA,
    SCRAPE_RUNS_SCHEMA,
    TEAM_ELO_SCHEMA,
    TEAM_MATCH_STATS_SCHEMA,
    align_to_schema,
)

SCHEMA_MANIFEST_VERSION_KEY = "version"
SCHEMA_MANIFEST_UPDATED_KEY = "updated_at"
SCHEMA_MANIFEST_MIGRATIONS_KEY = "applied_migrations"


@dataclass
class Lake:
    """Entry point for every read and write against the lake.

    :param root: filesystem path that contains (or will contain) the lake
    """

    root: Path
    _conn: duckdb.DuckDBPyConnection | None = None

    @property
    def layout(self) -> LakeLayout:
        return LakeLayout(self.root)

    def ensure_schema(self) -> None:
        """Materialize the directory skeleton and run pending migrations.

        Idempotent; safe to call at every process start.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        manifest = self._read_manifest()
        raw_applied = manifest.get(SCHEMA_MANIFEST_MIGRATIONS_KEY, [])
        assert isinstance(raw_applied, list)
        applied: list[dict[str, Any]] = [dict(m) for m in raw_applied]
        applied_versions = {int(m["version"]) for m in applied}

        version_raw = manifest.get(SCHEMA_MANIFEST_VERSION_KEY, 0)
        max_version = int(version_raw) if isinstance(version_raw, (int, str)) else 0
        for migration in MIGRATIONS:
            if migration.VERSION in applied_versions:
                continue
            migration.apply(self.layout)
            applied.append(
                {
                    "version": migration.VERSION,
                    "name": migration.NAME,
                    "applied_at": datetime.now(tz=timezone.utc).isoformat(),
                }
            )
            max_version = max(max_version, migration.VERSION)

        manifest[SCHEMA_MANIFEST_VERSION_KEY] = max_version
        manifest[SCHEMA_MANIFEST_UPDATED_KEY] = datetime.now(tz=timezone.utc).isoformat()
        manifest[SCHEMA_MANIFEST_MIGRATIONS_KEY] = applied
        self._write_manifest(manifest)

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Return a lazily-created DuckDB connection bound to this lake.

        The connection is in-memory; persistence lives in the Parquet files.
        Callers that need a short-lived connection should use
        :meth:`session` instead.

        :return: DuckDB connection with the lake root registered as a variable
        """
        if self._conn is None:
            self._conn = duckdb.connect(database=":memory:")
            self._conn.execute(
                "CREATE OR REPLACE MACRO lake_root() AS '{root}'".format(
                    root=str(self.root).replace("'", "''")
                )
            )
        return self._conn

    @contextmanager
    def session(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Context-manager variant of :meth:`connect` for short-lived jobs.

        :yield: DuckDB connection; closed automatically on exit
        """
        conn = duckdb.connect(database=":memory:")
        try:
            yield conn
        finally:
            conn.close()

    def close(self) -> None:
        """Close the long-lived DuckDB connection (if any)."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest_odds(
        self,
        snapshots: list[OddsSnapshot],
        *,
        provenance: IngestProvenance,
    ) -> IngestReport:
        """Write a batch of validated ``OddsSnapshot`` rows.

        Dedupe happens at write time: rows whose ``natural_key`` already
        exists in the target partition are dropped. This keeps re-runs of a
        scheduled scraper idempotent.

        :param snapshots: already-validated pydantic snapshots
        :param provenance: who produced these rows
        :return: report summarizing what landed where
        """
        del provenance
        if not snapshots:
            return IngestReport(rows_received=0, rows_written=0)

        rows = [self._snapshot_to_row(s) for s in snapshots]
        frame = pl.DataFrame(rows, schema=ODDS_SCHEMA)
        frame = align_to_schema(frame, ODDS_SCHEMA)

        # Partition by (bookmaker, market, season); write one file per group.
        report = IngestReport(rows_received=len(rows), rows_written=0)
        for (bookmaker, market, season), group in _group_by(
            frame, ("bookmaker", "market", "season")
        ):
            partition = self.layout.odds_partition(
                bookmaker=str(bookmaker), market=str(market), season=str(season)
            )
            written, skipped = self._append_parquet(
                partition=partition,
                frame=group,
                dedupe_cols=(
                    "bookmaker",
                    "bookmaker_event_id",
                    "market",
                    "market_params_hash",
                    "selection",
                    "captured_at",
                ),
                schema=ODDS_SCHEMA,
            )
            report = IngestReport(
                rows_received=report.rows_received,
                rows_written=report.rows_written + written,
                rows_skipped_duplicate=report.rows_skipped_duplicate + skipped,
                rows_rejected=report.rows_rejected,
                rejected_reasons=report.rejected_reasons,
                partitions_written=[*report.partitions_written, str(partition)],
            )
        return report

    def ingest_matches(
        self, matches: list[Match], *, provenance: IngestProvenance
    ) -> IngestReport:
        """Write a batch of validated ``Match`` rows and refresh the index.

        :param matches: already-validated matches
        :param provenance: who produced these rows
        :return: report summarizing what landed where
        """
        del provenance
        if not matches:
            return IngestReport(rows_received=0, rows_written=0)

        rows = [m.model_dump() for m in matches]
        for r in rows:
            r["league"] = (
                r["league"].value if hasattr(r["league"], "value") else r["league"]
            )
        frame = pl.DataFrame(rows)
        frame = align_to_schema(frame, MATCH_SCHEMA)

        report = IngestReport(rows_received=len(rows), rows_written=0)
        for (league, season), group in _group_by(frame, ("league", "season")):
            partition = self.layout.matches_partition(
                league=str(league), season=str(season)
            )
            written, skipped = self._append_parquet(
                partition=partition,
                frame=group,
                dedupe_cols=("match_id",),
                schema=MATCH_SCHEMA,
            )
            report = IngestReport(
                rows_received=report.rows_received,
                rows_written=report.rows_written + written,
                rows_skipped_duplicate=report.rows_skipped_duplicate + skipped,
                rejected_reasons=report.rejected_reasons,
                partitions_written=[*report.partitions_written, str(partition)],
            )
        self._refresh_match_index()
        return report

    def ingest_team_match_stats(
        self, stats: list[TeamMatchStats], *, provenance: IngestProvenance
    ) -> IngestReport:
        """Write per-team-per-match stats.

        :param stats: already-validated stat rows
        :param provenance: who produced these rows
        :return: report summarizing what landed where
        """
        del provenance
        if not stats:
            return IngestReport(rows_received=0, rows_written=0)

        rows = [s.model_dump() for s in stats]
        for r in rows:
            r["league"] = (
                r["league"].value if hasattr(r["league"], "value") else r["league"]
            )
        frame = pl.DataFrame(rows)
        frame = align_to_schema(frame, TEAM_MATCH_STATS_SCHEMA)

        report = IngestReport(rows_received=len(rows), rows_written=0)
        for (league, season), group in _group_by(frame, ("league", "season")):
            partition = self.layout.team_match_stats_partition(
                league=str(league), season=str(season)
            )
            written, skipped = self._append_parquet(
                partition=partition,
                frame=group,
                dedupe_cols=("match_id", "team"),
                schema=TEAM_MATCH_STATS_SCHEMA,
            )
            report = IngestReport(
                rows_received=report.rows_received,
                rows_written=report.rows_written + written,
                rows_skipped_duplicate=report.rows_skipped_duplicate + skipped,
                rejected_reasons=report.rejected_reasons,
                partitions_written=[*report.partitions_written, str(partition)],
            )
        return report

    def ingest_team_elo(
        self, elos: list[TeamElo], *, provenance: IngestProvenance
    ) -> IngestReport:
        """Write a batch of ClubElo snapshots.

        Dedupe key is ``(team, snapshot_date)``; partitioned by the month of
        the snapshot (``year_month=YYYY-MM``).

        :param elos: already-validated Elo rows
        :param provenance: who produced these rows
        :return: report summarizing what landed where
        """
        del provenance
        if not elos:
            return IngestReport(rows_received=0, rows_written=0)

        rows = [e.model_dump() for e in elos]
        frame = pl.DataFrame(rows)
        frame = align_to_schema(frame, TEAM_ELO_SCHEMA)
        frame = frame.with_columns(
            pl.col("snapshot_date").cast(pl.Date).dt.strftime("%Y-%m").alias("__ym__")
        )

        report = IngestReport(rows_received=len(rows), rows_written=0)
        for (year_month,), group in _group_by(frame, ("__ym__",)):
            group = group.drop("__ym__")
            partition = self.layout.team_elo_partition(year_month=str(year_month))
            written, skipped = self._append_parquet(
                partition=partition,
                frame=group,
                dedupe_cols=("team", "snapshot_date"),
                schema=TEAM_ELO_SCHEMA,
            )
            report = IngestReport(
                rows_received=report.rows_received,
                rows_written=report.rows_written + written,
                rows_skipped_duplicate=report.rows_skipped_duplicate + skipped,
                rejected_reasons=report.rejected_reasons,
                partitions_written=[*report.partitions_written, str(partition)],
            )
        return report

    def log_scrape_run(self, run: ScrapeRun) -> Path:
        """Append one audit row for a scheduled scraper execution.

        :param run: scrape-run record
        :return: parquet path that was appended to
        """
        payload = run.model_dump()
        payload["bookmaker"] = (
            run.bookmaker.value if run.bookmaker is not None else None
        )
        frame = pl.DataFrame([payload])
        frame = align_to_schema(frame, SCRAPE_RUNS_SCHEMA)

        year_month = run.started_at.astimezone(timezone.utc).strftime("%Y-%m")
        partition = self.layout.scrape_runs_partition(
            bookmaker=payload["bookmaker"] or "unknown", year_month=year_month
        )
        written, _ = self._append_parquet(
            partition=partition,
            frame=frame,
            dedupe_cols=("run_id",),
            schema=SCRAPE_RUNS_SCHEMA,
        )
        assert written <= 1
        return partition

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def read_odds(
        self,
        *,
        bookmaker: str | None = None,
        market: str | None = None,
        season: str | None = None,
        since: datetime | None = None,
    ) -> pl.DataFrame:
        """Union-by-name read over the odds partitions.

        :param bookmaker: restrict to one bookmaker slug
        :param market: restrict to one market code
        :param season: restrict to one ``YYYY-YY`` season
        :param since: keep only rows whose ``captured_at`` is ≥ ``since``
        :return: polars dataframe with the requested rows, or empty frame
        """
        files = self._resolve_partition_files(
            self.layout.odds_root,
            (
                ("bookmaker", bookmaker),
                ("market", market),
                ("season", season),
            ),
        )
        if not files:
            return pl.DataFrame(schema=ODDS_SCHEMA)
        df = pl.read_parquet(files)
        if since is not None:
            df = df.filter(pl.col("captured_at") >= since)
        return df

    def read_matches(
        self,
        *,
        league: str | None = None,
        season: str | None = None,
        since: date | None = None,
    ) -> pl.DataFrame:
        """Union-by-name read over the matches partitions.

        :param league: restrict to one league slug
        :param season: restrict to one season code
        :param since: keep only rows whose ``match_date`` is ≥ ``since``
        :return: polars dataframe with the requested rows, or empty frame
        """
        files = self._resolve_partition_files(
            self.layout.matches_root,
            (
                ("league", league),
                ("season", season),
            ),
            exclude_names=("match_index.parquet",),
        )
        if not files:
            return pl.DataFrame(schema=MATCH_SCHEMA)
        df = pl.read_parquet(files)
        if since is not None:
            df = df.filter(pl.col("match_date") >= since)
        return df

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_manifest(self) -> dict[str, Any]:
        path = self.layout.manifest
        if not path.exists():
            return {}
        data: dict[str, Any] = json.loads(path.read_text("utf-8"))
        return data

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        self.layout.manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _snapshot_to_row(snapshot: OddsSnapshot) -> dict[str, Any]:
        return {
            "bookmaker": snapshot.bookmaker.value,
            "bookmaker_event_id": snapshot.bookmaker_event_id,
            "match_id": snapshot.match_id,
            "match_label": snapshot.match_label,
            "match_date": snapshot.match_date,
            "season": snapshot.season,
            "league": snapshot.league.value if snapshot.league is not None else None,
            "home_team": snapshot.home_team,
            "away_team": snapshot.away_team,
            "market": snapshot.market.value,
            "market_params_json": json.dumps(
                snapshot.market_params, sort_keys=True, default=str
            ),
            "market_params_hash": snapshot.params_hash(),
            "selection": snapshot.selection,
            "payout": snapshot.payout,
            "captured_at": snapshot.captured_at,
            "source": snapshot.source,
            "run_id": snapshot.run_id,
            "raw_json": snapshot.raw_json,
        }

    def _append_parquet(
        self,
        *,
        partition: Path,
        frame: pl.DataFrame,
        dedupe_cols: tuple[str, ...],
        schema: pl.Schema,
    ) -> tuple[int, int]:
        """Append ``frame`` to ``partition``, skipping rows that duplicate existing keys.

        :param partition: partition directory (created if needed)
        :param frame: rows to write
        :param dedupe_cols: columns whose combination identifies a row uniquely
        :param schema: target polars schema (used for empty-frame allocation)
        :return: ``(rows_written, rows_skipped_duplicate)``
        """
        partition.mkdir(parents=True, exist_ok=True)

        existing_keys: set[tuple[object, ...]] = set()
        for existing in sorted(partition.glob("*.parquet")):
            df = pl.read_parquet(existing, columns=list(dedupe_cols))
            existing_keys.update(tuple(row) for row in df.iter_rows())

        if existing_keys:
            frame_with_key = frame.with_row_index("__row_idx__")
            key_series = frame_with_key.select(list(dedupe_cols)).rows()
            keep_mask = [tuple(k) not in existing_keys for k in key_series]
            kept = frame.filter(pl.Series(keep_mask))
            skipped = frame.height - kept.height
            frame = kept
        else:
            skipped = 0

        if frame.height == 0:
            return 0, skipped

        # Also drop duplicates within this batch.
        before = frame.height
        frame = frame.unique(subset=list(dedupe_cols), keep="first", maintain_order=True)
        skipped += before - frame.height

        if frame.height == 0:
            return 0, skipped

        target = partition / timestamped_filename(prefix="batch", ext="parquet")
        if target.exists():
            stem = target.stem
            suffix = 1
            while True:
                candidate = partition / f"{stem}-{suffix:03d}.parquet"
                if not candidate.exists():
                    target = candidate
                    break
                suffix += 1
        frame = align_to_schema(frame, schema)
        frame.write_parquet(target)
        return frame.height, skipped

    def _refresh_match_index(self) -> None:
        target = self.layout.matches_root / "match_index.parquet"
        glob = self.layout.matches_root / "league=*" / "season=*" / "*.parquet"
        paths = [p for p in self.layout.matches_root.glob("league=*/season=*/*.parquet")]
        if not paths:
            return
        df = pl.read_parquet(paths)
        df = df.select(
            ["match_id", "league", "season", "match_date", "home_team", "away_team"]
        ).unique()
        df.write_parquet(target)
        _ = glob

    @staticmethod
    def _resolve_partition_files(
        root: Path,
        filters: tuple[tuple[str, str | None], ...],
        *,
        exclude_names: tuple[str, ...] = (),
    ) -> list[Path]:
        """Enumerate parquet files under a hive-partitioned tree.

        :param root: table root (e.g. ``lake/odds``)
        :param filters: ordered ``(key, value)`` pairs that define the
            partition depth; ``None`` matches any value at that level
        :param exclude_names: filenames to skip (e.g. ``match_index.parquet``)
        :return: sorted list of ``.parquet`` paths (empty if nothing matches)
        """
        if not root.exists():
            return []
        parts: list[str] = []
        for key, value in filters:
            parts.append(f"{key}={value}" if value else f"{key}=*")
        parts.append("*.parquet")
        pattern = "/".join(parts)
        files = [p for p in root.glob(pattern) if p.name not in exclude_names]
        return sorted(files)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _group_by(
    frame: pl.DataFrame, cols: tuple[str, ...]
) -> Iterator[tuple[tuple[Any, ...], pl.DataFrame]]:
    for key, sub in frame.group_by(list(cols), maintain_order=True):
        yield tuple(key), sub
