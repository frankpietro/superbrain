"""Async ``httpx`` client for the Sisal hidden prematch-odds API.

Endpoints (all ``GET``, all unauthenticated, all JSON; see the sibling
``README.md`` for the full catalog):

* ``alberaturaPrematch`` — master sport/league tree.
* ``v1/schedaManifestazione/{timeFilter}/{competitionKey}`` — events for one
  league, with the default cluster's odds inlined.
* ``schedaAvvenimento/{eventKey}`` — every prematch market offered for one
  event (~130 markets per Serie A fixture, ~2 MB payload).

The client is deliberately small: it centralizes headers, retries, and rate
limiting so the parser and the orchestrator only deal with ``dict`` responses.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from types import TracebackType
from typing import Any

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = structlog.get_logger(__name__)

SISAL_API_BASE = "https://betting.sisal.it/api/lettura-palinsesto-sport/palinsesto"
SISAL_PREMATCH_BASE = f"{SISAL_API_BASE}/prematch"

# Akamai Bot Manager fronts ``betting.sisal.it`` and silently drops (read:
# times out) requests that don't carry a browser-shaped User-Agent. The
# spike ran with ``superbrain-spike/0.1`` and got 200s; that stopped
# working by the time we built the production client (see
# ``docs/knowledge.md`` → Sisal scraper gotcha). We mirror what the SPA
# itself sends from a recent Chrome build on macOS.
SISAL_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Origin": "https://www.sisal.it",
    "Referer": "https://www.sisal.it/scommesse-matchpoint/",
    "X-Auth-Channel": "62",
    "X-Country": "IT",
}

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MIN_INTERVAL_S = 1.0
DEFAULT_ENDPOINT_CONCURRENCY = 1

_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})


class SisalError(RuntimeError):
    """Unrecoverable failure while talking to the Sisal API."""

    def __init__(self, message: str, *, url: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class _RetryableHTTPError(Exception):
    """Internal marker: a response whose status is worth retrying."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"retryable HTTP status {response.status_code} on {response.request.url}")
        self.response = response


def _should_retry(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableHTTPError | httpx.TransportError | httpx.TimeoutException)


class _EndpointLimiter:
    """Per-endpoint concurrency + minimum-interval limiter.

    We keep one of these per *endpoint class* (tree / events / event-markets)
    so bursts against one endpoint don't starve the others.
    """

    def __init__(self, *, concurrency: int, min_interval_s: float) -> None:
        self._sem = asyncio.Semaphore(concurrency)
        self._min_interval = min_interval_s
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> None:
        await self._sem.acquire()
        async with self._lock:
            now = asyncio.get_event_loop().time()
            delay = self._min_interval - (now - self._last)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = asyncio.get_event_loop().time()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._sem.release()


class SisalClient:
    """Async wrapper around the three Sisal prematch endpoints we use.

    :param client: optional pre-built ``httpx.AsyncClient`` (useful for tests
        and for sharing a connection pool with other scrapers).
    :param headers: optional header overrides (merged over :data:`SISAL_DEFAULT_HEADERS`).
    :param timeout: per-request timeout in seconds.
    :param max_attempts: retry budget for transient errors (5xx, 429, network).
    :param min_interval_s: minimum spacing between successive requests to the
        same endpoint class.
    :param endpoint_concurrency: in-flight request cap per endpoint class.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        endpoint_concurrency: int = DEFAULT_ENDPOINT_CONCURRENCY,
    ) -> None:
        merged_headers = {**SISAL_DEFAULT_HEADERS, **(headers or {})}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers=merged_headers,
            http2=False,
        )
        if client is not None:
            self._client.headers.update(merged_headers)
        self._max_attempts = max_attempts
        self._limiters: dict[str, _EndpointLimiter] = {
            name: _EndpointLimiter(
                concurrency=endpoint_concurrency,
                min_interval_s=min_interval_s,
            )
            for name in ("tree", "events", "event_markets")
        }

    async def __aenter__(self) -> SisalClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_tree(self) -> dict[str, Any]:
        """Fetch the master discipline / manifestazione tree.

        :return: parsed JSON
        """
        url = f"{SISAL_PREMATCH_BASE}/alberaturaPrematch"
        return await self._get_json("tree", url)

    async def fetch_events(self, competition_key: str, *, time_filter: str = "0") -> dict[str, Any]:
        """Fetch events for one league, with the default-cluster odds inline.

        :param competition_key: ``"<sportId>-<competitionCode>"`` (e.g. ``"1-209"``).
        :param time_filter: SPA numeric time filter (``"0"`` = all upcoming).
        :return: parsed JSON
        """
        url = (
            f"{SISAL_PREMATCH_BASE}/v1/schedaManifestazione/"
            f"{time_filter}/{competition_key}"
            "?offerId=0&metaTplEnabled=true&deep=true"
        )
        return await self._get_json("events", url, extra_log={"competition_key": competition_key})

    async def fetch_event_markets(self, event_key: str) -> dict[str, Any]:
        """Fetch the full prematch market bundle for one event.

        :param event_key: either the composite ``"<codicePalinsesto>-<codiceAvvenimento>"``
            key or the numeric regulator id.
        :return: parsed JSON
        """
        url = f"{SISAL_PREMATCH_BASE}/schedaAvvenimento/{event_key}?offerId=0"
        return await self._get_json("event_markets", url, extra_log={"event_key": event_key})

    async def _get_json(
        self,
        endpoint_class: str,
        url: str,
        *,
        extra_log: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        limiter = self._limiters[endpoint_class]
        log_kwargs = {"endpoint": endpoint_class, "url": url, **(extra_log or {})}
        try:
            async for attempt in AsyncRetrying(
                reraise=True,
                stop=stop_after_attempt(self._max_attempts),
                wait=wait_exponential_jitter(initial=0.5, max=4.0, jitter=0.25),
                retry=retry_if_exception(_should_retry),
            ):
                with attempt:
                    async with limiter:
                        response = await self._client.get(url)
                    if response.status_code in _RETRYABLE_STATUSES:
                        log.warning(
                            "sisal.retryable_status",
                            status=response.status_code,
                            **log_kwargs,
                        )
                        raise _RetryableHTTPError(response)
                    if response.status_code >= 400:
                        raise SisalError(
                            f"HTTP {response.status_code} from Sisal: {_truncate(response.text)}",
                            url=url,
                            status=response.status_code,
                        )
                    try:
                        payload: Any = response.json()
                    except ValueError as e:
                        raise SisalError(
                            f"non-JSON body from {url}: {e}", url=url, status=response.status_code
                        ) from e
                    if not isinstance(payload, dict):
                        raise SisalError(
                            f"expected JSON object at {url}, got {type(payload).__name__}",
                            url=url,
                            status=response.status_code,
                        )
                    return payload
        except _RetryableHTTPError as e:
            raise SisalError(
                f"HTTP {e.response.status_code} after retries: {_truncate(e.response.text)}",
                url=url,
                status=e.response.status_code,
            ) from e
        except httpx.HTTPError as e:
            raise SisalError(f"network error against {url}: {e}", url=url) from e
        raise SisalError(f"unreachable: retry loop exited without a result for {url}", url=url)


def _truncate(text: str, limit: int = 200) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def available_endpoint_classes() -> Iterable[str]:
    return ("tree", "events", "event_markets")
