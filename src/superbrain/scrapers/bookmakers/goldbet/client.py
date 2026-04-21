"""Async HTTP client for Goldbet's hidden JSON API.

Goldbet (goldbet.it) is fronted by Akamai Bot Manager with JA3/TLS
fingerprinting. A plain ``httpx.AsyncClient`` gets 403'd at the edge
because its TLS ClientHello does not match Chrome's. The cheapest
fix that keeps the scraper out of a headless browser is
``curl_cffi``: it speaks Chrome's TLS fingerprint natively, and after
a single "warmup" GET against the SPA's homepage the Akamai cookies
(``_abck``, ``bm_sz``, ``ak_bmsc``) land in the cookie jar and the
hidden JSON endpoints start returning 200.

The Playwright fallback is deliberately not wired in here. If Goldbet
tightens the gate later, swap the bootstrap inside
:func:`_warmup_cookies` and everything above this module keeps
working.

Usage
-----

.. code-block:: python

    async with get_session() as client:
        events = await client.fetch_tournament_events(93)
        detail = await client.fetch_event_markets(
            id_tournament=93, id_event=events[0].event_id,
            id_aams_tournament=events[0].id_aams_tournament,
            id_aams_event=events[0].id_aams_event, tab_id=0,
        )
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import structlog
from curl_cffi.requests import AsyncSession, Response
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = structlog.get_logger(__name__)

BASE_URL = "https://www.goldbet.it"
WARMUP_URL = f"{BASE_URL}/scommesse/sport/calcio/"
IMPERSONATE_TARGET: Final = "chrome124"

# Mandatory headers required by every JSON endpoint. Omitting any one of
# ``X-Brand`` / ``X-IdCanale`` / ``X-AcceptConsent`` / ``X-Verticale`` yields
# 403 even when Akamai cookies are present.
_MANDATORY_HEADERS: dict[str, str] = {
    "X-Brand": "1",
    "X-IdCanale": "1",
    "X-AcceptConsent": "false",
    "X-Verticale": "1",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": WARMUP_URL,
}

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MIN_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class TournamentRef:
    """Identifiers needed to reach a tournament's listing endpoint."""

    slug: str
    id_tournament: int
    id_aams_tournament: int


TOP5_TOURNAMENTS: tuple[TournamentRef, ...] = (
    TournamentRef("serie-a", 93, 21),
    TournamentRef("premier-league", 26604, 86),
    TournamentRef("liga", 95, 79),
    TournamentRef("bundesliga", 84, 4),
    TournamentRef("ligue-1", 86, 14),
)


class _SessionLike(Protocol):
    """Minimal slice of ``curl_cffi.requests.AsyncSession`` we rely on.

    Narrowing the contract lets the test-suite substitute a fake without
    pulling the real library into a fixture.
    """

    async def get(self, url: str, *, headers: dict[str, str], timeout: float) -> Response: ...

    async def close(self) -> None: ...


class _RateLimiter:
    """Simple leaky-bucket: wait so successive calls are ``min_interval`` apart."""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._next_ready_at = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next_ready_at - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = time.monotonic()
            self._next_ready_at = now + self._min_interval


class GoldbetError(RuntimeError):
    """Base class for Goldbet-scraper network failures."""


class GoldbetForbiddenError(GoldbetError):
    """Raised when the edge (Akamai) rejects us with 403. Triggers refresh."""


class GoldbetTransientError(GoldbetError):
    """Raised on 429/5xx. Retriable via tenacity."""


@dataclass
class GoldbetClient:
    """Async Goldbet HTTP client with Akamai bootstrap + throttling + retries.

    The client owns one :class:`curl_cffi.requests.AsyncSession`, impersonating
    Chrome's TLS fingerprint. A one-shot "warmup" GET against the SPA's
    homepage seeds Akamai cookies before any JSON call; a 403 anywhere later
    triggers a single refresh before retries give up.

    Tests inject a fake via the ``session`` argument; production code should
    use :func:`get_session` instead.

    :param session: low-level HTTP session (None → constructed lazily)
    :param min_interval_seconds: rate-limit window, default 1.0 s
    :param timeout_seconds: per-request timeout, default 20.0 s
    :param max_attempts: tenacity attempt count for transient failures
    """

    session: _SessionLike | None = None
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = 3
    _owns_session: bool = field(default=False, init=False)
    _warmed: bool = field(default=False, init=False)
    _limiter: _RateLimiter = field(init=False)

    def __post_init__(self) -> None:
        self._limiter = _RateLimiter(self.min_interval_seconds)

    async def __aenter__(self) -> GoldbetClient:
        if self.session is None:
            self.session = AsyncSession(impersonate=IMPERSONATE_TARGET)
            self._owns_session = True
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Release the underlying HTTP session if the client owns it."""
        if self.session is not None and self._owns_session:
            try:
                await self.session.close()
            finally:
                self.session = None
                self._owns_session = False

    async def _warmup_cookies(self, *, force: bool = False) -> None:
        """Seed Akamai cookies by hitting the SPA's homepage once.

        :param force: bypass the one-shot cache and hit the warmup URL again
        """
        if self._warmed and not force:
            return
        assert self.session is not None
        logger.info("goldbet.warmup", url=WARMUP_URL, force=force)
        await self._limiter.wait()
        resp = await self.session.get(
            WARMUP_URL,
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=self.timeout_seconds,
        )
        if resp.status_code >= 400:
            raise GoldbetError(f"akamai warmup failed: HTTP {resp.status_code} for {WARMUP_URL}")
        self._warmed = True

    async def _get_json(self, url: str) -> Any:
        """GET ``url`` expecting JSON; retry on transient, refresh-then-retry on 403.

        :param url: fully-qualified Goldbet URL
        :return: parsed JSON payload
        :raises GoldbetError: when all retries fail
        """
        assert self.session is not None, "client used outside `async with`"
        session = self.session
        await self._warmup_cookies()

        async def _one_shot() -> Any:
            await self._limiter.wait()
            r = await session.get(url, headers=_MANDATORY_HEADERS, timeout=self.timeout_seconds)
            status = r.status_code
            if status == 403:
                raise GoldbetForbiddenError(f"403 at {url}")
            if status in {429, 502, 503, 504}:
                raise GoldbetTransientError(f"transient HTTP {status} at {url}")
            if status >= 400:
                raise GoldbetError(f"HTTP {status} at {url}")
            return r.json()  # type: ignore[no-untyped-call]

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_attempts),
                wait=wait_exponential_jitter(initial=1.0, max=10.0),
                retry=retry_if_exception_type(GoldbetTransientError),
                reraise=True,
            ):
                with attempt:
                    return await _one_shot()
        except GoldbetForbiddenError:
            logger.warning("goldbet.refresh_cookies", url=url)
            await self._warmup_cookies(force=True)
            return await _one_shot()
        except RetryError as e:  # defensive; reraise=True should have surfaced cause
            raise GoldbetError(f"exhausted retries for {url}") from e

    async def fetch_tournament_events(self, id_tournament: int) -> list[dict[str, Any]]:
        """Fetch the event-listing payload for one tournament (one league).

        Maps to ``GET /api/sport/pregame/getOverviewEventsAams/0/1/0/{id}/0/0/0``.

        :param id_tournament: Goldbet tournament id (e.g. 93 for Serie A)
        :return: list of event dicts (``leo`` array); empty if Goldbet hasn't
            published any fixtures
        """
        url = f"{BASE_URL}/api/sport/pregame/getOverviewEventsAams/0/1/0/{id_tournament}/0/0/0"
        payload = await self._get_json(url)
        leo = payload.get("leo") or []
        if not isinstance(leo, list):
            return []
        return [e for e in leo if isinstance(e, dict)]

    async def fetch_event_markets(
        self,
        *,
        id_aams_tournament: int,
        id_tournament: int,
        id_aams_event: str | int,
        id_event: int,
        tab_id: int = 0,
    ) -> dict[str, Any]:
        """Fetch the event-detail payload for one event / tab.

        Maps to
        ``GET /api/sport/pregame/getDetailsEventAams/{aams_t}/{t}/{aams_e}/{e}/{tab}/0``.

        The spike believed ``tab_id=0`` was the only value that returned odds.
        Empirically (2026-04-21), passing a tab block id (``tbI``, e.g. 3479
        for Principali, 3500 for Angoli) **also** returns odds-bearing
        markets for that tab — values that are *not* a real tbI return a
        tree-only payload with ``success: False``.

        :param id_aams_tournament: ``tai`` from the event listing
        :param id_tournament: ``ti`` from the event listing
        :param id_aams_event: ``pi`` from the event listing (may arrive as str)
        :param id_event: ``ei`` from the event listing
        :param tab_id: ``0`` for Principali (default), or a ``tbI`` from the
            tree (``lmtW``) for a specific tab block
        :return: full JSON payload; callers typically consume ``leo[0]["mmkW"]``
        """
        url = (
            f"{BASE_URL}/api/sport/pregame/getDetailsEventAams/"
            f"{id_aams_tournament}/{id_tournament}/"
            f"{id_aams_event}/{id_event}/{tab_id}/0"
        )
        payload = await self._get_json(url)
        return payload if isinstance(payload, dict) else {}


@asynccontextmanager
async def get_session(
    *,
    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = 3,
) -> AsyncIterator[GoldbetClient]:
    """Yield a ready-to-use :class:`GoldbetClient`.

    The client owns its underlying ``AsyncSession`` and releases it on exit.

    :param min_interval_seconds: rate-limit window between requests
    :param timeout_seconds: per-request timeout
    :param max_attempts: tenacity attempt count for transient failures
    :yield: an open :class:`GoldbetClient`
    """
    client = GoldbetClient(
        min_interval_seconds=min_interval_seconds,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )
    async with client:
        yield client
