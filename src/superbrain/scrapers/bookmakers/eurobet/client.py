"""Async dual-transport client for the Eurobet hidden-API.

Two endpoint classes live behind ``www.eurobet.it``:

1. **Public navigation.** The ``/_next/data/...`` SSG blobs, the
   ``/prematch-homepage-service/...`` homepage feeds, and the
   ``/prematch-menu-service/...`` sport-tree feeds are open to plain
   ``httpx`` without any TLS impersonation or tenant headers.
2. **Per-event / per-meeting markets.** The ``/detail-service/...``
   endpoints are gated by Cloudflare Bot Fight Mode. Plain ``httpx``
   is rejected with HTTP 403 / ``cf-mitigated: challenge``. Requests
   go through with ``curl_cffi.requests.AsyncSession`` using
   ``impersonate="chrome124"`` (any modern Chrome profile works).
   Two mandatory tenant headers apply: ``X-EB-MarketId: IT`` and
   ``X-EB-PlatformId: WEB``; without them the Spring backend returns
   a ``code=-99`` validation error inside a 200 envelope.

The client is deliberately thin: callers see ``dict`` responses and
don't care which transport served them.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Mapping
from types import TracebackType
from typing import Any

import httpx
import structlog
from curl_cffi.requests import AsyncSession as _CFFIAsyncSession
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = structlog.get_logger(__name__)

EUROBET_BASE = "https://www.eurobet.it"

PUBLIC_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "superbrain-eurobet/0.1 (+https://github.com/frankpietro/superbrain)",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Referer": f"{EUROBET_BASE}/it/scommesse/calcio",
}

CFFI_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Referer": f"{EUROBET_BASE}/it/scommesse/calcio",
    "X-EB-MarketId": "IT",
    "X-EB-PlatformId": "WEB",
}

DEFAULT_IMPERSONATE = "chrome124"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MIN_INTERVAL_S = 1.0

_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 502, 503, 504})
_BUILD_ID_RE = re.compile(r'"buildId"\s*:\s*"([^"]+)"')


class EurobetError(RuntimeError):
    """Unrecoverable error while talking to Eurobet."""

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        status: int | None = None,
        code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.code = code


class _RetryableHTTPError(Exception):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"retryable HTTP {status} on {url}")
        self.status = status
        self.url = url


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, _RetryableHTTPError):
        return True
    if isinstance(exc, httpx.TransportError | httpx.TimeoutException):
        return True
    return exc.__class__.__name__ in {"ConnectionError", "Timeout", "RequestException"}


class _RateLimiter:
    """Simple min-interval limiter shared across coroutines."""

    def __init__(self, min_interval_s: float) -> None:
        self._min = min_interval_s
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            delay = self._min - (now - self._last)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = asyncio.get_event_loop().time()


class EurobetClient:
    """Async dual-transport client for Eurobet.

    :param httpx_client: optional pre-built ``httpx.AsyncClient`` (tests).
    :param public_headers: overrides for the plain-httpx path.
    :param cffi_headers: overrides for the curl_cffi path.
    :param timeout: per-request timeout seconds.
    :param max_attempts: retry budget for 429/502/503/504/network errors.
    :param min_interval_s: minimum spacing between any two outbound
        requests (shared across both transports).
    :param impersonate: curl_cffi browser fingerprint profile.
    """

    def __init__(
        self,
        *,
        httpx_client: httpx.AsyncClient | None = None,
        public_headers: Mapping[str, str] | None = None,
        cffi_headers: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        impersonate: str = DEFAULT_IMPERSONATE,
    ) -> None:
        merged_public = {**PUBLIC_DEFAULT_HEADERS, **(public_headers or {})}
        self._owns_httpx = httpx_client is None
        self._httpx = httpx_client or httpx.AsyncClient(
            timeout=timeout,
            headers=merged_public,
            follow_redirects=True,
            http2=False,
        )
        if httpx_client is not None:
            self._httpx.headers.update(merged_public)

        self._cffi_headers = {**CFFI_DEFAULT_HEADERS, **(cffi_headers or {})}
        self._timeout = timeout
        self._impersonate = impersonate
        self._max_attempts = max_attempts
        self._limiter = _RateLimiter(min_interval_s)
        self._cffi_session: Any | None = None

    async def __aenter__(self) -> EurobetClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close every managed transport."""
        if self._owns_httpx:
            await self._httpx.aclose()
        if self._cffi_session is not None:
            with contextlib.suppress(Exception):
                await self._cffi_session.close()
            self._cffi_session = None

    # ------------------------------------------------------------------
    # Public navigation endpoints (plain httpx)
    # ------------------------------------------------------------------

    async def fetch_landing_build_id(self) -> str:
        """Scrape ``buildId`` from the ``/it/scommesse/calcio`` landing HTML.

        The Next.js build id rotates each deploy; callers that hit
        ``/_next/data/{build_id}/...`` need a fresh value and should
        cache this for about an hour.

        :return: the raw build-id string embedded in ``__NEXT_DATA__``
        """
        url = f"{EUROBET_BASE}/it/scommesse/calcio"
        await self._limiter.wait()
        try:
            resp = await self._httpx.get(url)
        except httpx.HTTPError as e:
            raise EurobetError(f"network error on landing: {e}", url=url) from e
        if resp.status_code >= 400:
            raise EurobetError(
                f"HTTP {resp.status_code} on landing",
                url=url,
                status=resp.status_code,
            )
        m = _BUILD_ID_RE.search(resp.text)
        if not m:
            raise EurobetError("could not find buildId in landing HTML", url=url)
        return m.group(1)

    async def fetch_top_disciplines(self, discipline_alias: str = "calcio") -> dict[str, Any]:
        """Fetch the homepage ``top-disciplines`` carousel feed.

        :param discipline_alias: Eurobet discipline slug (default: calcio).
        :return: parsed JSON
        """
        url = (
            f"{EUROBET_BASE}/prematch-homepage-service/api/v2/sport-schedule"
            f"/services/top-disciplines/1/{discipline_alias}"
        )
        return await self._get_httpx_json(url)

    async def fetch_sport_list(self, discipline_alias: str = "calcio") -> dict[str, Any]:
        """Fetch the authoritative meeting tree for the discipline.

        :param discipline_alias: Eurobet discipline slug (default: calcio).
        :return: parsed JSON
        """
        url = (
            f"{EUROBET_BASE}/prematch-menu-service/api/v2/sport-schedule"
            f"/services/sport-list/{discipline_alias}"
        )
        return await self._get_httpx_json(url)

    async def fetch_meeting_next(
        self,
        *,
        build_id: str,
        discipline_alias: str,
        meeting_slug: str,
    ) -> dict[str, Any]:
        """Fetch a per-meeting Next.js SSG blob (SEO + nav, no events).

        Kept so the scraper can harvest the build id and drive route
        warming. Plain ``httpx`` is sufficient.

        :param build_id: the current Next.js build id
        :param discipline_alias: discipline slug (e.g. ``calcio``)
        :param meeting_slug: fully qualified meeting slug (e.g. ``it-serie-a``)
        :return: parsed JSON
        """
        url = (
            f"{EUROBET_BASE}/_next/data/{build_id}/it/scommesse/"
            f"{discipline_alias}/{meeting_slug}.json"
        )
        params = {
            "language": "it",
            "discipline": discipline_alias,
            "meeting": meeting_slug,
        }
        return await self._get_httpx_json(url, params=params)

    # ------------------------------------------------------------------
    # Markets endpoints (curl_cffi - Cloudflare-gated)
    # ------------------------------------------------------------------

    async def fetch_meeting(
        self,
        *,
        discipline_alias: str,
        meeting_slug: str,
        prematch: bool = True,
        live: bool = False,
    ) -> dict[str, Any]:
        """Fetch the per-meeting detail-service payload.

        The result's ``dataGroupList`` contains per-date event tiles
        with ``eventInfo`` (programCode, eventCode, aliasUrl, teams,
        kickoff). This is the authoritative list of fixtures for a
        meeting.

        :param discipline_alias: discipline slug (e.g. ``calcio``)
        :param meeting_slug: fully qualified meeting slug
        :param prematch: include prematch markets
        :param live: include live markets
        :return: parsed JSON envelope (``code``/``description``/``result``)
        """
        path = f"/detail-service/sport-schedule/services/meeting/{discipline_alias}/{meeting_slug}"
        params = {"prematch": int(prematch), "live": int(live)}
        referer = f"{EUROBET_BASE}/it/scommesse/{discipline_alias}/{meeting_slug}"
        return await self._get_cffi_json(EUROBET_BASE + path, params=params, referer=referer)

    async def fetch_event(
        self,
        *,
        discipline_alias: str,
        meeting_slug: str,
        event_slug: str,
        group_alias: str | None = None,
        prematch: bool = True,
        live: bool = False,
    ) -> dict[str, Any]:
        """Fetch the per-event detail-service payload.

        Without ``group_alias`` the server returns the default
        "piu-giocate" subset (~14 bet groups / ~200 odds). Passing
        ``group_alias="tutte"`` returns the full per-event dump (up to
        ~7-8 MB / 280+ bet groups / 16k+ odds close to kickoff).

        :param discipline_alias: discipline slug (e.g. ``calcio``)
        :param meeting_slug: fully qualified meeting slug
        :param event_slug: event alias (e.g. ``napoli-cremonese-202604242045``)
        :param group_alias: optional bet-group slice alias
        :param prematch: include prematch markets
        :param live: include live markets
        :return: parsed JSON envelope
        """
        path = (
            f"/detail-service/sport-schedule/services/event/"
            f"{discipline_alias}/{meeting_slug}/{event_slug}"
        )
        if group_alias:
            path = f"{path}/{group_alias}"
        params = {"prematch": int(prematch), "live": int(live)}
        referer = f"{EUROBET_BASE}/it/scommesse/{discipline_alias}/{meeting_slug}/{event_slug}"
        return await self._get_cffi_json(EUROBET_BASE + path, params=params, referer=referer)

    # ------------------------------------------------------------------
    # Transport internals
    # ------------------------------------------------------------------

    async def _get_httpx_json(
        self, url: str, *, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential_jitter(initial=0.5, max=4.0, jitter=0.25),
            retry=retry_if_exception(_should_retry),
        ):
            with attempt:
                await self._limiter.wait()
                try:
                    resp = await self._httpx.get(url, params=params)
                except httpx.HTTPError as e:
                    raise EurobetError(f"network error on {url}: {e}", url=url) from e
                if resp.status_code in _RETRYABLE_STATUSES:
                    log.warning(
                        "eurobet.retryable_status",
                        transport="httpx",
                        status=resp.status_code,
                        url=url,
                    )
                    raise _RetryableHTTPError(resp.status_code, url)
                if resp.status_code >= 400:
                    raise EurobetError(
                        f"HTTP {resp.status_code} on {url}: {_truncate(resp.text)}",
                        url=url,
                        status=resp.status_code,
                    )
                try:
                    payload = resp.json()
                except ValueError as e:
                    raise EurobetError(
                        f"non-JSON body from {url}: {e}",
                        url=url,
                        status=resp.status_code,
                    ) from e
                if not isinstance(payload, dict):
                    raise EurobetError(
                        f"expected JSON object from {url}, got {type(payload).__name__}",
                        url=url,
                        status=resp.status_code,
                    )
                return payload
        raise EurobetError(f"unreachable: retry loop exited on {url}", url=url)

    async def _get_cffi_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        referer: str | None = None,
    ) -> dict[str, Any]:
        session = await self._ensure_cffi_session()
        headers = dict(self._cffi_headers)
        if referer:
            headers["Referer"] = referer

        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential_jitter(initial=0.5, max=4.0, jitter=0.25),
            retry=retry_if_exception(_should_retry),
        ):
            with attempt:
                await self._limiter.wait()
                try:
                    resp = await session.get(
                        url,
                        params=dict(params) if params else None,
                        headers=headers,
                        timeout=self._timeout,
                        impersonate=self._impersonate,
                    )
                except Exception as e:  # curl_cffi raises its own types
                    if _should_retry(e):
                        raise _RetryableHTTPError(-1, url) from e
                    raise EurobetError(f"network error on {url}: {e}", url=url) from e
                status = int(getattr(resp, "status_code", 0))
                if status in _RETRYABLE_STATUSES:
                    log.warning(
                        "eurobet.retryable_status",
                        transport="cffi",
                        status=status,
                        url=url,
                    )
                    raise _RetryableHTTPError(status, url)
                if status >= 400:
                    raise EurobetError(
                        f"HTTP {status} on {url}: {_truncate(resp.text)}",
                        url=url,
                        status=status,
                    )
                try:
                    payload = resp.json()
                except ValueError as e:
                    raise EurobetError(
                        f"non-JSON body from {url}: {e}",
                        url=url,
                        status=status,
                    ) from e
                if not isinstance(payload, dict):
                    raise EurobetError(
                        f"expected JSON object from {url}, got {type(payload).__name__}",
                        url=url,
                        status=status,
                    )
                code = payload.get("code")
                if isinstance(code, int) and code != 1:
                    raise EurobetError(
                        f"Eurobet app-level error code={code} on {url}: "
                        f"{_truncate(str(payload.get('description') or payload))}",
                        url=url,
                        status=status,
                        code=code,
                    )
                return payload
        raise EurobetError(f"unreachable: retry loop exited on {url}", url=url)

    async def _ensure_cffi_session(self) -> Any:
        if self._cffi_session is None:
            self._cffi_session = _CFFIAsyncSession()
        return self._cffi_session


def _truncate(text: str | Any, limit: int = 200) -> str:
    s = str(text)
    collapsed = " ".join(s.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


__all__ = [
    "CFFI_DEFAULT_HEADERS",
    "DEFAULT_IMPERSONATE",
    "EUROBET_BASE",
    "PUBLIC_DEFAULT_HEADERS",
    "EurobetClient",
    "EurobetError",
]
