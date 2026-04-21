"""Eurobet prematch scraper (phase 3).

Public API:

* :class:`EurobetClient` — dual-transport async client (httpx + curl_cffi)
* :func:`discover_events` — top-disciplines + per-meeting event discovery
* :func:`parse_event_markets` — per-event JSON → ``OddsSnapshot`` rows
* :func:`scrape` — end-to-end orchestrator consumed by the scheduler
"""

from superbrain.scrapers.bookmakers.eurobet.client import EurobetClient, EurobetError
from superbrain.scrapers.bookmakers.eurobet.markets import (
    ParsedEvent,
    parse_event_markets,
    parse_event_meta,
)
from superbrain.scrapers.bookmakers.eurobet.navigation import (
    EUROBET_LEAGUE_MEETINGS,
    EurobetEventRef,
    discover_events,
)
from superbrain.scrapers.bookmakers.eurobet.scraper import (
    EurobetScrapeResult,
    scrape,
)

__all__ = [
    "EUROBET_LEAGUE_MEETINGS",
    "EurobetClient",
    "EurobetError",
    "EurobetEventRef",
    "EurobetScrapeResult",
    "ParsedEvent",
    "discover_events",
    "parse_event_markets",
    "parse_event_meta",
    "scrape",
]
