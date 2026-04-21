"""Goldbet production scraper — orchestrator.

Ties together :mod:`.client` and :mod:`.markets` and drives a scheduled
run:

1. For each requested league, fetch the event listing
   (``getOverviewEventsAams``).
2. For each event, fetch the tab tree via
   ``getDetailsEventAams/.../0/0`` (tab ``0`` returns the Principali
   tab *and* the tree of other tabs with no extra cost).
3. For each discovered tab block (``tbI`` in ``lmtW``), fetch that
   tab's odds via ``getDetailsEventAams/.../{tbI}/0``. Spike note: the
   Goldbet JS client was believed to use ``idMacroTab=0`` exclusively;
   empirically (2026-04-21) passing a real ``tbI`` also returns
   odds-bearing markets, massively expanding per-event coverage.
4. Parse each payload into :class:`OddsSnapshot` rows via
   :func:`parse_markets`.
5. Batch-ingest via ``Lake.ingest_odds`` and write one ``ScrapeRun``
   row for the whole execution.

Missing markets, missing events, and non-top-5 leagues are not fatal:
the orchestrator logs them, continues, and still writes the
``ScrapeRun`` audit row with a status reflecting the outcome. The
only thing that aborts a run is the inability to bootstrap the Akamai
session; the scraper contract requires every scheduled run to leave
an audit trail.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

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
from superbrain.scrapers.bookmakers.goldbet.client import (
    TOP5_TOURNAMENTS,
    GoldbetClient,
    TournamentRef,
    get_session,
)
from superbrain.scrapers.bookmakers.goldbet.markets import (
    LEAGUE_BY_ID,
    build_event_meta,
    make_unmapped_log,
    parse_markets,
)

logger = structlog.get_logger(__name__)

SCRAPER_NAME = "goldbet"
SOURCE_TAG = "goldbet-scraper"
DEFAULT_EVENT_CONCURRENCY = 3


async def scrape(
    lake: Lake,
    *,
    leagues: Sequence[League] | None = None,
    run_id: str | None = None,
    client: GoldbetClient | None = None,
    event_concurrency: int = DEFAULT_EVENT_CONCURRENCY,
    actor: str = "goldbet-scraper",
) -> IngestReport:
    """Run one full Goldbet scrape and ingest the result into the lake.

    :param lake: :class:`Lake` receiving ``ingest_odds`` + ``log_scrape_run``
    :param leagues: optional whitelist; defaults to all top-5 leagues
    :param run_id: optional scrape-run identifier (UUID4 if omitted)
    :param client: optional pre-built :class:`GoldbetClient` (tests inject
        one backed by ``respx``); when ``None`` a fresh session is opened
    :param event_concurrency: semaphore size for per-event fetches
    :param actor: provenance tag forwarded to :class:`IngestProvenance`
    :return: merged :class:`IngestReport` across all events
    """
    resolved_run_id = run_id or f"goldbet-{uuid.uuid4().hex[:12]}"
    started_at = datetime.now(tz=UTC)
    tournaments = _resolve_tournaments(leagues)

    log = logger.bind(run_id=resolved_run_id)
    log.info("goldbet.scrape_start", tournaments=[t.slug for t in tournaments])

    all_snapshots: list[OddsSnapshot] = []
    status = "success"
    error_message: str | None = None

    try:
        if client is None:
            async with get_session() as owned_client:
                all_snapshots = await _collect_snapshots(
                    owned_client,
                    tournaments=tournaments,
                    run_id=resolved_run_id,
                    event_concurrency=event_concurrency,
                )
        else:
            all_snapshots = await _collect_snapshots(
                client,
                tournaments=tournaments,
                run_id=resolved_run_id,
                event_concurrency=event_concurrency,
            )
    except Exception as e:  # never raise out of scrape() — contract
        status = "failed"
        error_message = str(e)
        log.exception("goldbet.scrape_failed", error=str(e))

    provenance = IngestProvenance(
        source=SOURCE_TAG,
        run_id=resolved_run_id,
        actor=actor,
        captured_at=started_at,
        bookmaker=Bookmaker.GOLDBET,
    )
    if all_snapshots:
        ingest_report = lake.ingest_odds(all_snapshots, provenance=provenance)
    else:
        ingest_report = IngestReport(rows_received=0, rows_written=0)

    finished_at = datetime.now(tz=UTC)
    lake.log_scrape_run(
        ScrapeRun(
            run_id=resolved_run_id,
            bookmaker=Bookmaker.GOLDBET,
            scraper=SCRAPER_NAME,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            rows_written=ingest_report.rows_written,
            rows_rejected=ingest_report.rows_rejected,
            error_message=error_message,
            host=_safe_hostname(),
        )
    )
    log.info(
        "goldbet.scrape_done",
        status=status,
        rows_written=ingest_report.rows_written,
        rows_received=ingest_report.rows_received,
        rows_rejected=ingest_report.rows_rejected,
        duration_s=(finished_at - started_at).total_seconds(),
    )
    return ingest_report


async def _collect_snapshots(
    client: GoldbetClient,
    *,
    tournaments: Sequence[TournamentRef],
    run_id: str,
    event_concurrency: int,
) -> list[OddsSnapshot]:
    unmapped = make_unmapped_log()
    semaphore = asyncio.Semaphore(event_concurrency)
    snapshots: list[OddsSnapshot] = []

    for tournament in tournaments:
        events = await _fetch_events_safe(client, tournament)
        if not events:
            continue

        captured_at = datetime.now(tz=UTC)
        tasks = [
            _fetch_event_snapshots(
                client=client,
                semaphore=semaphore,
                event=event,
                tournament=tournament,
                captured_at=captured_at,
                run_id=run_id,
                unmapped=unmapped,
            )
            for event in events
        ]
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "goldbet.event_task_failed",
                    tournament=tournament.slug,
                    error=str(result),
                )
                continue
            snapshots.extend(result)

    return snapshots


async def _fetch_events_safe(
    client: GoldbetClient, tournament: TournamentRef
) -> list[dict[str, Any]]:
    try:
        return await client.fetch_tournament_events(tournament.id_tournament)
    except Exception as e:  # never raise up
        logger.warning("goldbet.event_list_failed", tournament=tournament.slug, error=str(e))
        return []


async def _fetch_event_snapshots(
    *,
    client: GoldbetClient,
    semaphore: asyncio.Semaphore,
    event: dict[str, Any],
    tournament: TournamentRef,
    captured_at: datetime,
    run_id: str,
    unmapped: Any,
) -> list[OddsSnapshot]:
    """Fetch and parse every tab's markets for one event.

    :return: list of validated snapshots; empty on any hard failure
    """
    async with semaphore:
        try:
            return await _fetch_event_snapshots_unlocked(
                client=client,
                event=event,
                tournament=tournament,
                captured_at=captured_at,
                run_id=run_id,
                unmapped=unmapped,
            )
        except Exception as e:  # defensive blanket catch per task
            logger.warning(
                "goldbet.event_failed",
                event_id=event.get("ei"),
                tournament=tournament.slug,
                error=str(e),
            )
            return []


async def _fetch_event_snapshots_unlocked(
    *,
    client: GoldbetClient,
    event: dict[str, Any],
    tournament: TournamentRef,
    captured_at: datetime,
    run_id: str,
    unmapped: Any,
) -> list[OddsSnapshot]:
    id_aams_tournament = int(event.get("tai") or tournament.id_aams_tournament)
    id_tournament = int(event.get("ti") or tournament.id_tournament)
    id_event = event.get("ei")
    id_aams_event = event.get("pi")
    if id_event is None or id_aams_event is None:
        return []

    league_hint = LEAGUE_BY_ID.get(id_tournament)
    meta = build_event_meta(
        event,
        captured_at=captured_at,
        source=SOURCE_TAG,
        run_id=run_id,
        league_hint=league_hint,
    )
    if meta is None:
        logger.debug("goldbet.event_meta_unparseable", event_id=id_event)
        return []

    snapshots: list[OddsSnapshot] = []

    # 1) Principali tab (tab=0). This payload also carries ``lmtW`` — the tree
    #    of every other tab block — so we don't pay an extra hop to discover
    #    tabs.
    principal_payload = await client.fetch_event_markets(
        id_aams_tournament=id_aams_tournament,
        id_tournament=id_tournament,
        id_aams_event=id_aams_event,
        id_event=int(id_event),
        tab_id=0,
    )
    snapshots.extend(parse_markets(principal_payload, meta, unmapped=unmapped))

    # 2) Each non-Principali tab block. ``lmtW`` is the tree; each entry's
    #    ``tbI`` is the macroTab value that actually returns odds for that
    #    tab. Empirically confirmed 2026-04-21.
    tab_ids = _discover_tab_ids(principal_payload)
    for tab_id in tab_ids:
        tab_payload = await client.fetch_event_markets(
            id_aams_tournament=id_aams_tournament,
            id_tournament=id_tournament,
            id_aams_event=id_aams_event,
            id_event=int(id_event),
            tab_id=tab_id,
        )
        snapshots.extend(parse_markets(tab_payload, meta, unmapped=unmapped))

    return snapshots


def _discover_tab_ids(payload: dict[str, Any]) -> list[int]:
    """Extract every ``tbI`` from ``lmtW``, excluding the Principali tab (3479).

    :param payload: any Goldbet event-detail payload (tab=0 or tree-only)
    :return: ordered list of additional tab block ids worth fetching
    """
    lmt = payload.get("lmtW") or []
    if not isinstance(lmt, list):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for entry in lmt:
        if not isinstance(entry, dict):
            continue
        tbi = entry.get("tbI")
        if not isinstance(tbi, int) or tbi in seen:
            continue
        if tbi == 3479:
            continue  # already fetched as tab=0
        seen.add(tbi)
        out.append(tbi)
    return out


def _resolve_tournaments(
    leagues: Iterable[League] | None,
) -> list[TournamentRef]:
    if not leagues:
        return list(TOP5_TOURNAMENTS)
    wanted = set(leagues)
    selected: list[TournamentRef] = []
    for tournament in TOP5_TOURNAMENTS:
        league = LEAGUE_BY_ID.get(tournament.id_tournament)
        if league is not None and league in wanted:
            selected.append(tournament)
    return selected


def _safe_hostname() -> str | None:
    try:
        return socket.gethostname()
    except OSError:
        return None
