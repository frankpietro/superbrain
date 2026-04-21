"""Sisal hidden-API prematch odds scraper (production).

Uses plain ``httpx`` against ``betting.sisal.it/api/...``. No Playwright, no
OCR. Ships a client, a market parser, and an orchestrator; the scheduler
(phase 10) imports :func:`scrape` directly.
"""

from superbrain.scrapers.bookmakers.sisal.client import (
    SISAL_API_BASE,
    SISAL_DEFAULT_HEADERS,
    SisalClient,
    SisalError,
)
from superbrain.scrapers.bookmakers.sisal.markets import parse_event_markets
from superbrain.scrapers.bookmakers.sisal.scraper import (
    SISAL_LEAGUE_KEYS,
    SisalScrapeResult,
    scrape,
)

__all__ = [
    "SISAL_API_BASE",
    "SISAL_DEFAULT_HEADERS",
    "SISAL_LEAGUE_KEYS",
    "SisalClient",
    "SisalError",
    "SisalScrapeResult",
    "parse_event_markets",
    "scrape",
]
