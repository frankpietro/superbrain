"""Phase-2 historical backfill orchestrator.

Fetches top-5 European leagues x 2020-21..2024-25 from free sources
(football-data.co.uk, Understat by default; FBref + ClubElo opt-in), merges
them via :mod:`superbrain.scrapers.historical.merge`, and writes the
resulting ``Match`` + ``TeamMatchStats`` rows to a data lake through
``Lake.ingest_*``.

Example::

    uv run python scripts/backfill_historical.py \
        --lake /tmp/sb-phase2 \
        --leagues serie_a,premier_league \
        --seasons 2023-24,2024-25 \
        --sources football_data,understat

Running twice against the same lake writes zero new rows on the second
invocation (dedupe is enforced inside ``Lake._append_parquet``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import socket
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import polars as pl

from superbrain.core.models import (
    IngestProvenance,
    League,
    ScrapeRun,
    TeamElo,
)
from superbrain.data.connection import Lake
from superbrain.scrapers.historical.merge import merge_sources
from superbrain.scrapers.historical.sources import (
    clubelo,
    fbref,
    football_data,
    understat,
)

logger = logging.getLogger("superbrain.backfill")


DEFAULT_LEAGUES: tuple[League, ...] = (
    League.SERIE_A,
    League.PREMIER_LEAGUE,
    League.LA_LIGA,
    League.BUNDESLIGA,
    League.LIGUE_1,
)

DEFAULT_SEASONS: tuple[str, ...] = (
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
)

DEFAULT_SOURCES: tuple[str, ...] = ("football_data", "understat")
ALL_SOURCES: tuple[str, ...] = ("football_data", "understat", "fbref", "clubelo")


@dataclass
class LeagueSeasonReport:
    league: str
    season: str
    sources: list[str]
    matches_received: int = 0
    matches_written: int = 0
    matches_skipped: int = 0
    stats_received: int = 0
    stats_written: int = 0
    stats_skipped: int = 0
    elo_written: int = 0
    rejected: int = 0
    rejected_reasons: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class BackfillReport:
    started_at: str
    finished_at: str | None = None
    lake: str = ""
    per_league_season: list[LeagueSeasonReport] = field(default_factory=list)
    total_matches_written: int = 0
    total_stats_written: int = 0
    total_elo_written: int = 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase-2 historical-data backfill orchestrator")
    p.add_argument("--lake", required=True, type=Path, help="Lake root directory")
    p.add_argument(
        "--leagues",
        default=",".join(lg.value for lg in DEFAULT_LEAGUES),
        help="comma-separated league slugs",
    )
    p.add_argument(
        "--seasons",
        default=",".join(DEFAULT_SEASONS),
        help="comma-separated season codes (YYYY-YY)",
    )
    p.add_argument(
        "--sources",
        default=",".join(DEFAULT_SOURCES),
        help=(
            "comma-separated source tags. Supported: "
            + ",".join(ALL_SOURCES)
            + ". FBref and ClubElo are opt-in because they are slow/heavy."
        ),
    )
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def _parse_leagues(s: str) -> list[League]:
    slugs = [v.strip() for v in s.split(",") if v.strip()]
    out: list[League] = []
    for slug in slugs:
        try:
            out.append(League(slug))
        except ValueError as exc:
            raise SystemExit(f"unknown league slug: {slug}") from exc
    return out


def _parse_seasons(s: str) -> list[str]:
    return [v.strip() for v in s.split(",") if v.strip()]


def _parse_sources(s: str) -> list[str]:
    out = [v.strip() for v in s.split(",") if v.strip()]
    bad = [v for v in out if v not in ALL_SOURCES]
    if bad:
        raise SystemExit(f"unknown source(s): {bad} (supported: {list(ALL_SOURCES)})")
    return out


async def run_backfill(
    lake: Lake,
    *,
    leagues: list[League],
    seasons: list[str],
    sources: list[str],
) -> BackfillReport:
    """Fetch → merge → ingest for every (league, season) pair.

    :param lake: lake to write into; must already be ``ensure_schema``'d
    :param leagues: list of leagues to process
    :param seasons: list of canonical season codes
    :param sources: list of source tags
    :return: structured backfill report
    """
    report = BackfillReport(
        started_at=datetime.now(tz=UTC).isoformat(timespec="seconds"),
        lake=str(lake.root),
    )
    actor = f"backfill@{socket.gethostname()}"
    headers = {"User-Agent": "superbrain/0.2 (+historical-backfill)"}

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for league in leagues:
            for season in seasons:
                rpt = await _process_league_season(
                    lake=lake,
                    league=league,
                    season=season,
                    sources=sources,
                    http_client=client,
                    actor=actor,
                )
                report.per_league_season.append(rpt)
                report.total_matches_written += rpt.matches_written
                report.total_stats_written += rpt.stats_written
                report.total_elo_written += rpt.elo_written

    report.finished_at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    return report


async def _process_league_season(
    *,
    lake: Lake,
    league: League,
    season: str,
    sources: list[str],
    http_client: httpx.AsyncClient,
    actor: str,
) -> LeagueSeasonReport:
    rpt = LeagueSeasonReport(league=league.value, season=season, sources=list(sources))
    started = datetime.now(tz=UTC)
    run_id = f"bf-{uuid.uuid4().hex[:12]}"
    ingested_at = datetime.now(tz=UTC)

    fd_df: pl.DataFrame | None = None
    us_df: pl.DataFrame | None = None
    fb_df: pl.DataFrame | None = None

    try:
        if "football_data" in sources:
            logger.info("football_data: %s %s", league.value, season)
            fd_df = await football_data.fetch_league_season(league, season, client=http_client)
        if "understat" in sources:
            logger.info("understat: %s %s", league.value, season)
            us_df = await understat.fetch_league_season(league, season, client=http_client)
        if "fbref" in sources:
            logger.info("fbref: %s %s (this may take minutes)", league.value, season)
            fb_df = await asyncio.to_thread(fbref.fetch_league_season, league, season)

        merged = merge_sources(
            league=league,
            season=season,
            football_data=fd_df,
            understat=us_df,
            fbref=fb_df,
            ingested_at=ingested_at,
        )
        rpt.rejected = merged.rejected
        rpt.rejected_reasons = dict(merged.rejected_reasons)

        provenance = IngestProvenance(
            source="backfill",
            run_id=run_id,
            actor=actor,
            captured_at=ingested_at,
            note=f"{league.value}/{season} from {','.join(sources)}",
        )
        match_report = lake.ingest_matches(merged.matches, provenance=provenance)
        stats_report = lake.ingest_team_match_stats(merged.team_match_stats, provenance=provenance)
        rpt.matches_received = match_report.rows_received
        rpt.matches_written = match_report.rows_written
        rpt.matches_skipped = match_report.rows_skipped_duplicate
        rpt.stats_received = stats_report.rows_received
        rpt.stats_written = stats_report.rows_written
        rpt.stats_skipped = stats_report.rows_skipped_duplicate

        if "clubelo" in sources:
            rpt.elo_written = _backfill_clubelo(
                lake=lake,
                league=league,
                season=season,
                ingested_at=ingested_at,
                provenance=provenance,
            )

        status = "ok"
    except Exception as exc:
        logger.exception("league-season failed: %s %s", league.value, season)
        rpt.errors.append(f"{type(exc).__name__}: {exc}")
        status = "failed"

    lake.log_scrape_run(
        ScrapeRun(
            run_id=run_id,
            bookmaker=None,
            scraper=f"historical:{','.join(sources)}",
            started_at=started,
            finished_at=datetime.now(tz=UTC),
            status=status,
            rows_written=rpt.matches_written + rpt.stats_written + rpt.elo_written,
            rows_rejected=rpt.rejected,
            error_message=None if status == "ok" else "; ".join(rpt.errors),
            host=socket.gethostname(),
        )
    )
    return rpt


def _backfill_clubelo(
    *,
    lake: Lake,
    league: League,
    season: str,
    ingested_at: datetime,
    provenance: IngestProvenance,
) -> int:
    snapshot_date = _season_end_date(season)
    df = clubelo.fetch_snapshot(snapshot_date, leagues=[league])
    if df.height == 0:
        return 0
    rows: list[TeamElo] = []
    for r in df.iter_rows(named=True):
        elo = r.get("elo")
        if elo is None or r.get("club") is None:
            continue
        rows.append(
            TeamElo(
                team=str(r["club"]),
                country=str(r.get("country") or ""),
                snapshot_date=snapshot_date,
                elo=float(elo),
                rank=int(r["rank"]) if r.get("rank") is not None else None,
                source="clubelo",
                ingested_at=ingested_at,
            )
        )
    rep = lake.ingest_team_elo(rows, provenance=provenance)
    return rep.rows_written


def _season_end_date(season: str) -> date:
    """Return a plausible end-of-season snapshot date for ClubElo.

    :param season: canonical season code (``YYYY-YY``)
    :return: 1 June of the season's end year
    """
    if len(season) != 7 or season[4] != "-":
        raise ValueError(f"expected YYYY-YY, got {season!r}")
    end_year = int(season[:2] + season[5:7])
    return date(end_year, 6, 1)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    leagues = _parse_leagues(args.leagues)
    seasons = _parse_seasons(args.seasons)
    sources = _parse_sources(args.sources)

    lake = Lake(root=args.lake)
    lake.ensure_schema()

    report = asyncio.run(run_backfill(lake, leagues=leagues, seasons=seasons, sources=sources))
    payload = {
        **asdict(report),
        "per_league_season": [asdict(r) for r in report.per_league_season],
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
