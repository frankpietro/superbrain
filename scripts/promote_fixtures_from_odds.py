"""Backfill the ``matches`` table from already-captured odds rows.

Older lakes (created before the odds-ingest path started promoting
fixtures) have an empty ``matches`` table even though the odds table
carries every upcoming fixture denormalised. This script reads the
current ``odds`` partitions, derives one ``Match`` per unique
``match_id``, and appends the gap into ``matches``. It is idempotent
— the underlying ``Lake.ingest_matches`` dedupes on ``match_id``.

Usage::

    uv run python scripts/promote_fixtures_from_odds.py \\
        --lake data/lake [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from superbrain.core.models import (  # noqa: E402
    IngestProvenance,
    League,
    Match,
    compute_match_id,
)
from superbrain.data.connection import Lake  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lake",
        type=Path,
        default=REPO_ROOT / "data" / "lake",
        help="path to the lake root (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be written without touching the lake",
    )
    return parser.parse_args()


def _derive_matches(odds: pl.DataFrame, *, ingested_at: datetime) -> list[Match]:
    """Build one ``Match`` per unique ``match_id`` in the odds frame."""
    required = ["match_id", "league", "season", "match_date", "home_team", "away_team"]
    fixtures = (
        odds.select([*required, "bookmaker"])
        .filter(pl.col("match_id").is_not_null() & pl.col("league").is_not_null())
        .unique(subset=["match_id"], keep="first")
        .sort("match_date")
    )

    matches: list[Match] = []
    for row in fixtures.iter_rows(named=True):
        league_value = row["league"]
        try:
            league = League(league_value)
        except ValueError:
            continue
        home = (row["home_team"] or "").strip()
        away = (row["away_team"] or "").strip()
        if not home or not away:
            continue
        match_date = row["match_date"]
        if not isinstance(match_date, date):
            continue
        expected = compute_match_id(home, away, match_date, league)
        if row["match_id"] != expected:
            continue
        matches.append(
            Match(
                match_id=row["match_id"],
                league=league,
                season=row["season"],
                match_date=match_date,
                home_team=home,
                away_team=away,
                home_goals=None,
                away_goals=None,
                source=f"odds:{row['bookmaker']}",
                ingested_at=ingested_at,
            )
        )
    return matches


def main() -> int:
    args = _parse_args()
    lake = Lake(args.lake)
    lake.ensure_schema()

    odds = lake.read_odds()
    if odds.is_empty():
        print("odds table is empty; nothing to promote")
        return 0

    now = datetime.now(tz=UTC)
    matches = _derive_matches(odds, ingested_at=now)
    existing = lake._existing_match_ids(pairs=[(m.league.value, m.season) for m in matches])
    new = [m for m in matches if m.match_id not in existing]

    print(
        f"odds_rows={odds.height} unique_fixtures={len(matches)} "
        f"already_in_matches={len(matches) - len(new)} to_promote={len(new)}"
    )

    if args.dry_run:
        for m in new[:5]:
            print(
                f"  would promote {m.match_id} {m.league.value} {m.match_date} {m.home_team} vs {m.away_team}"
            )
        return 0

    if not new:
        return 0

    report = lake.ingest_matches(
        new,
        provenance=IngestProvenance(
            source="odds-promotion-backfill",
            run_id=f"odds-promotion-backfill-{now.strftime('%Y%m%dT%H%M%S%fZ')}",
            actor="scripts/promote_fixtures_from_odds.py",
            captured_at=now,
        ),
    )
    print(
        f"wrote rows={report.rows_written} skipped={report.rows_skipped_duplicate} "
        f"partitions={len(report.partitions_written)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
