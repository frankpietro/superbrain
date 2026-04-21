"""Eurobet prematch scraper orchestrator.

Ties :class:`EurobetClient`, :func:`discover_events`, and
:func:`parse_event_markets` together into the production entry point
:func:`scrape`. Concurrency and error handling mirror the Sisal /
Goldbet scrapers so phase-10 scheduling is uniform.

Concurrency:

* ``top-disciplines`` + per-meeting discovery happens sequentially inside
  :func:`discover_events` (limited by the client's shared rate limiter).
* Per-event market fetches run under a configurable ``asyncio.Semaphore``
  (default 3 concurrent requests; rate-limited to ~1 req/s regardless).

Failures at the league / meeting / event level are logged and counted;
they never abort the whole run. The function always returns a valid
:class:`EurobetScrapeResult` and always writes a matching row to
``scrape_runs``.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import structlog

from superbrain.core.models import (
    Bookmaker,
    IngestProvenance,
    IngestReport,
    League,
    OddsSnapshot,
    ScrapeRun,
)
from superbrain.data.connection import Lake
from superbrain.scrapers.bookmakers.eurobet.client import EurobetClient, EurobetError
from superbrain.scrapers.bookmakers.eurobet.markets import parse_event_markets
from superbrain.scrapers.bookmakers.eurobet.navigation import (
    DISCIPLINE_CALCIO,
    EUROBET_LEAGUE_MEETINGS,
    EurobetEventRef,
    discover_events,
)

log = structlog.get_logger(__name__)


_DEFAULT_EVENT_CONCURRENCY = 3


@dataclass
class EurobetScrapeResult:
    """Rich return value for the Eurobet scraper.

    ``ingest_report`` is what phase-10 cares about most; the per-league
    and unmapped-market counters make the run log and live-test
    assertions useful.
    """

    run_id: str
    started_at: datetime
    finished_at: datetime
    status: str
    rows_written: int
    rows_received: int
    rows_rejected: int
    per_league_events: dict[str, int] = field(default_factory=dict)
    per_market_rows: Counter[str] = field(default_factory=Counter)
    unmapped_markets: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    ingest_report: IngestReport | None = None


async def scrape(
    lake: Lake,
    *,
    leagues: list[League] | list[str] | None = None,
    run_id: str | None = None,
    client: EurobetClient | None = None,
    event_concurrency: int = _DEFAULT_EVENT_CONCURRENCY,
    captured_at: datetime | None = None,
    discipline_alias: str = DISCIPLINE_CALCIO,
    group_alias: str | None = None,
) -> EurobetScrapeResult:
    """Run the Eurobet prematch scrape end-to-end.

    :param lake: :class:`Lake` the results are ingested into.
    :param leagues: list of leagues to scrape (:class:`League` enums or
        the matching string slugs). Defaults to the top-5 European
        leagues that Eurobet publishes.
    :param run_id: optional run identifier; a random UUID4 is generated
        when omitted.
    :param client: optional pre-built :class:`EurobetClient` (tests).
    :param event_concurrency: max in-flight per-event market requests.
    :param captured_at: timestamp attached to every emitted snapshot;
        defaults to ``datetime.now(UTC)``.
    :param discipline_alias: Eurobet discipline slug (default ``calcio``).
    :param group_alias: optional bet-group slice (``tutte`` for the full
        per-event dump). When ``None`` Eurobet serves ``piu-giocate``.
    :return: :class:`EurobetScrapeResult` summarizing the run.
    """
    resolved_run_id = run_id or uuid4().hex
    started_at = datetime.now(UTC)
    captured_at = captured_at or started_at
    selected = _resolve_leagues(leagues)

    result = EurobetScrapeResult(
        run_id=resolved_run_id,
        started_at=started_at,
        finished_at=started_at,
        status="success",
        rows_written=0,
        rows_received=0,
        rows_rejected=0,
    )
    owns_client = client is None
    active_client = client or EurobetClient()

    try:
        snapshots = await _collect_snapshots(
            client=active_client,
            leagues=selected,
            discipline_alias=discipline_alias,
            group_alias=group_alias,
            captured_at=captured_at,
            run_id=resolved_run_id,
            event_concurrency=event_concurrency,
            result=result,
        )
        if snapshots:
            provenance = IngestProvenance(
                source="eurobet.scraper",
                run_id=resolved_run_id,
                actor="eurobet-scraper",
                captured_at=captured_at,
                bookmaker=Bookmaker.EUROBET,
                note=f"leagues={','.join(sorted(lg.value for lg in selected))}",
            )
            try:
                ingest_report = lake.ingest_odds(snapshots, provenance=provenance)
            except Exception as e:  # pragma: no cover - lake is a hard-dep path
                log.error("eurobet.scrape.ingest_failed", error=str(e))
                result.errors.append(f"ingest_failed:{e}")
                ingest_report = IngestReport(
                    rows_received=len(snapshots),
                    rows_written=0,
                    rows_rejected=len(snapshots),
                )
                result.status = "partial"
            result.ingest_report = ingest_report
            result.rows_written = ingest_report.rows_written
            result.rows_received = ingest_report.rows_received
            result.rows_rejected = ingest_report.rows_rejected
        else:
            result.ingest_report = IngestReport(rows_received=0, rows_written=0)
    except Exception as e:  # pragma: no cover - belt and braces
        log.error("eurobet.scrape.unexpected_error", error=str(e))
        result.errors.append(f"unexpected:{e}")
        result.status = "failed"
    finally:
        if owns_client:
            await active_client.aclose()

    result.finished_at = datetime.now(UTC)
    if result.errors and result.status == "success":
        result.status = "partial"

    _write_scrape_run_log(lake=lake, result=result)
    log.info(
        "eurobet.scrape.done",
        run_id=resolved_run_id,
        status=result.status,
        rows_written=result.rows_written,
        per_league_events=result.per_league_events,
        unmapped_markets=dict(result.unmapped_markets.most_common(10)),
        errors=result.errors,
    )
    return result


async def _collect_snapshots(
    *,
    client: EurobetClient,
    leagues: list[League],
    discipline_alias: str,
    group_alias: str | None,
    captured_at: datetime,
    run_id: str,
    event_concurrency: int,
    result: EurobetScrapeResult,
) -> list[OddsSnapshot]:
    top_errors: list[str] = []
    meeting_errors: list[str] = []
    events_per_league = await discover_events(
        client,
        leagues=leagues,
        discipline_alias=discipline_alias,
        top_disciplines_errors=top_errors,
        per_meeting_errors=meeting_errors,
    )
    for msg in top_errors:
        result.errors.append(f"top_disciplines:{msg}")
    for msg in meeting_errors:
        result.errors.append(f"meeting:{msg}")

    sem = asyncio.Semaphore(event_concurrency)
    all_snapshots: list[OddsSnapshot] = []

    for league in leagues:
        refs = events_per_league.get(league, [])
        result.per_league_events[league.value] = len(refs)
        if not refs:
            continue
        tasks = [
            asyncio.create_task(
                _fetch_and_parse_event(
                    client=client,
                    sem=sem,
                    ref=ref,
                    league=league,
                    discipline_alias=discipline_alias,
                    group_alias=group_alias,
                    captured_at=captured_at,
                    run_id=run_id,
                    result=result,
                )
            )
            for ref in refs
        ]
        chunks = await asyncio.gather(*tasks, return_exceptions=False)
        for chunk in chunks:
            all_snapshots.extend(chunk)

    return all_snapshots


async def _fetch_and_parse_event(
    *,
    client: EurobetClient,
    sem: asyncio.Semaphore,
    ref: EurobetEventRef,
    league: League,
    discipline_alias: str,
    group_alias: str | None,
    captured_at: datetime,
    run_id: str,
    result: EurobetScrapeResult,
) -> list[OddsSnapshot]:
    async with sem:
        try:
            payload = await client.fetch_event(
                discipline_alias=discipline_alias,
                meeting_slug=ref.meeting_slug,
                event_slug=ref.event_slug,
                group_alias=group_alias,
            )
        except EurobetError as e:
            log.warning(
                "eurobet.scrape.event_markets_failed",
                league=league.value,
                event_id=ref.event_id,
                meeting=ref.meeting_slug,
                error=str(e),
            )
            result.errors.append(f"event_markets:{ref.event_id}:{e}")
            return []
    try:
        snapshots, unmapped = parse_event_markets(
            payload,
            league=league,
            captured_at=captured_at,
            run_id=run_id,
        )
    except Exception as e:  # pragma: no cover - defensive parser guard
        log.warning(
            "eurobet.scrape.parse_failed",
            league=league.value,
            event_id=ref.event_id,
            error=str(e),
        )
        result.errors.append(f"parse:{ref.event_id}:{e}")
        return []
    if unmapped:
        for desc, count in unmapped.items():
            if desc not in result.unmapped_markets:
                log.info(
                    "eurobet.scrape.unmapped_market",
                    market=desc,
                    event_id=ref.event_id,
                    occurrences=count,
                )
        result.unmapped_markets.update(unmapped)
    for snap in snapshots:
        result.per_market_rows[snap.market.value] += 1
    return snapshots


def _resolve_leagues(leagues: list[League] | list[str] | None) -> list[League]:
    if leagues is None:
        return list(EUROBET_LEAGUE_MEETINGS.keys())
    out: list[League] = []
    for entry in leagues:
        if isinstance(entry, League):
            out.append(entry)
        else:
            out.append(League(entry))
    unknown = [lg for lg in out if lg not in EUROBET_LEAGUE_MEETINGS]
    if unknown:
        raise ValueError(f"no Eurobet meeting slug for leagues: {unknown}")
    return out


def _write_scrape_run_log(*, lake: Lake, result: EurobetScrapeResult) -> None:
    try:
        run = ScrapeRun(
            run_id=result.run_id,
            bookmaker=Bookmaker.EUROBET,
            scraper="eurobet.prematch",
            started_at=result.started_at,
            finished_at=result.finished_at,
            status=result.status,
            rows_written=result.rows_written,
            rows_rejected=result.rows_rejected,
            error_message="; ".join(result.errors)[:1024] if result.errors else None,
            host=None,
        )
        lake.log_scrape_run(run)
    except Exception as e:  # pragma: no cover - defensive
        log.error("eurobet.scrape.run_log_failed", error=str(e))


__all__ = [
    "EurobetScrapeResult",
    "scrape",
]
