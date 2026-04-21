"""Lake layout.

The Parquet lake is hive-partitioned. Every ingest writes one file per
scrape (or per day); DuckDB reads across partitions via ``read_parquet`` with
``hive_partitioning=True``.

``Lake.ensure_schema`` materializes the directory skeleton and a
``schema_manifest.json`` so that downstream code can detect-and-migrate the
lake even when it starts from a fresh clone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class LakeLayout:
    """Resolved paths for every table under a lake root."""

    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "schema_manifest.json"

    @property
    def odds_root(self) -> Path:
        return self.root / "odds"

    @property
    def matches_root(self) -> Path:
        return self.root / "matches"

    @property
    def team_match_stats_root(self) -> Path:
        return self.root / "team_match_stats"

    @property
    def scrape_runs_root(self) -> Path:
        return self.root / "scrape_runs"

    @property
    def simulation_runs_root(self) -> Path:
        return self.root / "simulation_runs"

    @property
    def team_elo_root(self) -> Path:
        return self.root / "team_elo"

    def iter_table_roots(self) -> list[Path]:
        return [
            self.odds_root,
            self.matches_root,
            self.team_match_stats_root,
            self.scrape_runs_root,
            self.simulation_runs_root,
            self.team_elo_root,
        ]

    def odds_partition(self, *, bookmaker: str, market: str, season: str) -> Path:
        return (
            self.odds_root
            / f"bookmaker={bookmaker}"
            / f"market={market}"
            / f"season={season}"
        )

    def matches_partition(self, *, league: str, season: str) -> Path:
        return self.matches_root / f"league={league}" / f"season={season}"

    def team_match_stats_partition(self, *, league: str, season: str) -> Path:
        return self.team_match_stats_root / f"league={league}" / f"season={season}"

    def scrape_runs_partition(self, *, bookmaker: str, year_month: str) -> Path:
        return (
            self.scrape_runs_root
            / f"bookmaker={bookmaker}"
            / f"year_month={year_month}"
        )

    def simulation_runs_partition(self, *, created_date: str) -> Path:
        return self.simulation_runs_root / f"created_date={created_date}"

    def team_elo_partition(self, *, year_month: str) -> Path:
        return self.team_elo_root / f"year_month={year_month}"


def timestamped_filename(prefix: str = "batch", ext: str = "parquet") -> str:
    """Timestamped filename that sorts lexicographically.

    :param prefix: filename prefix
    :param ext: filename extension (without leading dot)
    :return: ``{prefix}-{YYYYMMDDTHHMMSSZ}.{ext}``
    """
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{ts}.{ext}"
