"""Goldbet hidden-API scraper.

Public entry point: :func:`superbrain.scrapers.bookmakers.goldbet.scrape`.

The scraper sits in front of Goldbet's Angular JSON gateway under
``https://www.goldbet.it/api/sport/...``. Goldbet is fronted by Akamai
Bot Manager with JA3 fingerprinting; see :mod:`.client` for the
bootstrap (``curl_cffi`` Chrome impersonation).
"""

from __future__ import annotations

from superbrain.scrapers.bookmakers.goldbet.client import (
    TOP5_TOURNAMENTS,
    GoldbetClient,
    TournamentRef,
    get_session,
)
from superbrain.scrapers.bookmakers.goldbet.scraper import scrape

__all__ = [
    "TOP5_TOURNAMENTS",
    "GoldbetClient",
    "TournamentRef",
    "get_session",
    "scrape",
]
