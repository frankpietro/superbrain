"""Sisal prematch scraper orchestrator.

Ties :class:`SisalClient` and :func:`parse_event_markets` together into the
production entry point :func:`scrape` that the phase-10 scheduler will call.

Concurrency:

* tree ``alberaturaPrematch`` is fetched once per run (cached in-process for
  up to an hour across repeated :func:`scrape` calls).
* For each league we fetch the events listing (serially across leagues to
  respect the per-endpoint rate limit inside :class:`SisalClient`).
* For each event we fetch the full market bundle under a configurable
  concurrency cap (``event_concurrency``, default ``4``).

Failures at the league level or at the event level are logged and counted;
they never abort the whole run. The function always returns a valid
:class:`IngestReport` and always writes a matching row to ``scrape_runs``.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
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
from superbrain.scrapers.bookmakers.sisal.client import SisalClient, SisalError
from superbrain.scrapers.bookmakers.sisal.markets import parse_event_markets

log = structlog.get_logger(__name__)


SISAL_LEAGUE_KEYS: dict[League, str] = {
    League.SERIE_A: "1-209",
    League.PREMIER_LEAGUE: "1-331",
    League.BUNDESLIGA: "1-228",
    League.LA_LIGA: "1-570",
    League.LIGUE_1: "1-781",
}


_DEFAULT_EVENT_CONCURRENCY = 4
_DEFAULT_TREE_TTL_S = 3600.0


@dataclass
class _TreeCache:
    ttl_s: float
    fetched_at: float = 0.0
    payload: dict[str, Any] | None = None

    def get(self) -> dict[str, Any] | None:
        if self.payload is None:
            return None
        if (time.monotonic() - self.fetched_at) > self.ttl_s:
            return None
        return self.payload

    def put(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.fetched_at = time.monotonic()


_TREE_CACHE = _TreeCache(ttl_s=_DEFAULT_TREE_TTL_S)


@dataclass
class SisalScrapeResult:
    """Rich return value for the scraper.

    ``ingest_report`` is what phase 10 cares about most; ``per_league_events``
    and ``unmapped_markets`` make the run log and live-test assertions
    useful.
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
    client: SisalClient | None = None,
    event_concurrency: int = _DEFAULT_EVENT_CONCURRENCY,
    tree_ttl_s: float = _DEFAULT_TREE_TTL_S,
    captured_at: datetime | None = None,
) -> SisalScrapeResult:
    """Run the Sisal prematch scrape end-to-end.

    :param lake: :class:`Lake` the results are ingested into.
    :param leagues: list of leagues to scrape (:class:`League` enums or the
        matching string slugs). Defaults to all top-5 European leagues.
    :param run_id: optional run identifier; a random UUID4 is generated when
        omitted.
    :param client: optional pre-built :class:`SisalClient` (mostly for
        testing; the scraper closes it on exit only if it created it).
    :param event_concurrency: max in-flight event-markets requests.
    :param tree_ttl_s: how long to treat a cached ``alberaturaPrematch``
        response as fresh (seconds).
    :param captured_at: timestamp attached to every emitted snapshot; when
        omitted, ``datetime.now(UTC)`` is used.
    :return: :class:`SisalScrapeResult` summarizing the run.
    """
    _TREE_CACHE.ttl_s = tree_ttl_s

    resolved_run_id = run_id or uuid4().hex
    started_at = datetime.now(UTC)
    captured_at = captured_at or started_at
    selected = _resolve_leagues(leagues)

    result = SisalScrapeResult(
        run_id=resolved_run_id,
        started_at=started_at,
        finished_at=started_at,
        status="success",
        rows_written=0,
        rows_received=0,
        rows_rejected=0,
    )
    owns_client = client is None
    active_client = client or SisalClient()

    try:
        snapshots = await _collect_snapshots(
            client=active_client,
            leagues=selected,
            captured_at=captured_at,
            run_id=resolved_run_id,
            event_concurrency=event_concurrency,
            result=result,
        )
        if snapshots:
            provenance = IngestProvenance(
                source="sisal.scraper",
                run_id=resolved_run_id,
                actor="sisal-scraper",
                captured_at=captured_at,
                bookmaker=Bookmaker.SISAL,
                note=f"leagues={','.join(sorted(lg.value for lg in selected))}",
            )
            try:
                ingest_report = lake.ingest_odds(snapshots, provenance=provenance)
            except Exception as e:  # pragma: no cover - lake is a hard-dep path
                log.error("sisal.scrape.ingest_failed", error=str(e))
                result.errors.append(f"ingest_failed:{e}")
                ingest_report = IngestReport(
                    rows_received=len(snapshots), rows_written=0, rows_rejected=len(snapshots)
                )
                result.status = "partial"
            result.ingest_report = ingest_report
            result.rows_written = ingest_report.rows_written
            result.rows_received = ingest_report.rows_received
            result.rows_rejected = ingest_report.rows_rejected
        else:
            result.ingest_report = IngestReport(rows_received=0, rows_written=0)
    except Exception as e:  # pragma: no cover - belt and braces
        log.error("sisal.scrape.unexpected_error", error=str(e))
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
        "sisal.scrape.done",
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
    client: SisalClient,
    leagues: list[League],
    captured_at: datetime,
    run_id: str,
    event_concurrency: int,
    result: SisalScrapeResult,
) -> list[OddsSnapshot]:
    try:
        await _ensure_tree(client)
    except SisalError as e:
        log.warning("sisal.scrape.tree_failed", error=str(e))
        result.errors.append(f"tree:{e}")

    sem = asyncio.Semaphore(event_concurrency)
    all_snapshots: list[OddsSnapshot] = []

    for league in leagues:
        competition_key = SISAL_LEAGUE_KEYS[league]
        try:
            events_payload = await client.fetch_events(competition_key)
        except SisalError as e:
            log.warning(
                "sisal.scrape.events_failed",
                league=league.value,
                competition_key=competition_key,
                error=str(e),
            )
            result.errors.append(f"events:{league.value}:{e}")
            continue

        events = events_payload.get("avvenimentoFeList") or []
        if not isinstance(events, list):
            log.warning(
                "sisal.scrape.events_shape_invalid",
                league=league.value,
                type=type(events).__name__,
            )
            events = []
        result.per_league_events[league.value] = len(events)

        tasks = [
            asyncio.create_task(
                _fetch_and_parse_event(
                    client=client,
                    sem=sem,
                    event=event,
                    league=league,
                    captured_at=captured_at,
                    run_id=run_id,
                    result=result,
                )
            )
            for event in events
        ]
        if not tasks:
            continue
        chunks = await asyncio.gather(*tasks, return_exceptions=False)
        for chunk in chunks:
            all_snapshots.extend(chunk)

    return all_snapshots


async def _ensure_tree(client: SisalClient) -> None:
    cached = _TREE_CACHE.get()
    if cached is not None:
        log.debug("sisal.scrape.tree_cache_hit")
        return
    payload = await client.fetch_tree()
    _TREE_CACHE.put(payload)


async def _fetch_and_parse_event(
    *,
    client: SisalClient,
    sem: asyncio.Semaphore,
    event: dict[str, Any],
    league: League,
    captured_at: datetime,
    run_id: str,
    result: SisalScrapeResult,
) -> list[OddsSnapshot]:
    event_key = str(event.get("key") or "")
    if not event_key:
        return []
    async with sem:
        try:
            markets_payload = await client.fetch_event_markets(event_key)
        except SisalError as e:
            log.warning(
                "sisal.scrape.event_markets_failed",
                league=league.value,
                event_key=event_key,
                error=str(e),
            )
            result.errors.append(f"event_markets:{event_key}:{e}")
            return []
    try:
        snapshots, unmapped = parse_event_markets(
            markets_payload,
            league=league,
            captured_at=captured_at,
            run_id=run_id,
        )
    except Exception as e:  # pragma: no cover - defensive parser guard
        log.warning(
            "sisal.scrape.parse_failed",
            league=league.value,
            event_key=event_key,
            error=str(e),
        )
        result.errors.append(f"parse:{event_key}:{e}")
        return []
    if unmapped:
        # First time we see a given descrizione in this run, log it at INFO.
        for desc, count in unmapped.items():
            if desc not in result.unmapped_markets:
                log.info(
                    "sisal.scrape.unmapped_market",
                    market=desc,
                    event_key=event_key,
                    occurrences=count,
                )
        result.unmapped_markets.update(unmapped)
    for snap in snapshots:
        result.per_market_rows[snap.market.value] += 1
    return snapshots


def _resolve_leagues(leagues: list[League] | list[str] | None) -> list[League]:
    if leagues is None:
        return list(SISAL_LEAGUE_KEYS.keys())
    out: list[League] = []
    for entry in leagues:
        if isinstance(entry, League):
            out.append(entry)
        else:
            out.append(League(entry))
    # Filter to the set we actually have keys for (everything in the top 5 today).
    unknown = [lg for lg in out if lg not in SISAL_LEAGUE_KEYS]
    if unknown:
        raise ValueError(f"no Sisal competition key for leagues: {unknown}")
    return out


def _write_scrape_run_log(*, lake: Lake, result: SisalScrapeResult) -> None:
    try:
        run = ScrapeRun(
            run_id=result.run_id,
            bookmaker=Bookmaker.SISAL,
            scraper="sisal.prematch",
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
        log.error("sisal.scrape.run_log_failed", error=str(e))


def reset_tree_cache() -> None:
    """Drop the cached ``alberaturaPrematch`` payload (tests + manual refresh)."""
    _TREE_CACHE.payload = None
    _TREE_CACHE.fetched_at = 0.0


__all__ = [
    "SISAL_LEAGUE_KEYS",
    "SisalScrapeResult",
    "reset_tree_cache",
    "scrape",
]
