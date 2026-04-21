"""Tests for :mod:`superbrain.scrapers.bookmakers.goldbet.client`.

The client sits on top of ``curl_cffi.requests.AsyncSession``. Mocking that
library directly is awkward (it's a C-extension wrapper around libcurl),
and ``respx`` only intercepts ``httpx``. So the tests substitute a small
fake ``_SessionLike`` implementation that is injected into
:class:`GoldbetClient` via its ``session`` argument; that gives
deterministic control over status codes, payloads, retry behaviour, and
the Akamai refresh path without spinning up a real TLS session.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

from superbrain.scrapers.bookmakers.goldbet.client import (
    BASE_URL,
    WARMUP_URL,
    GoldbetClient,
    GoldbetError,
)


@dataclass
class FakeResponse:
    status_code: int
    _payload: Any = None
    content: bytes = b""

    def json(self) -> Any:
        return self._payload


@dataclass
class FakeSession:
    """Scriptable stand-in for ``AsyncSession``.

    The ``handler`` callable receives the URL and the requested headers and
    must return a :class:`FakeResponse`. Each invocation is also recorded
    under ``calls`` so the tests can assert sequencing / header content.
    """

    handler: Callable[[str, dict[str, str]], FakeResponse]
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    closed: bool = False

    async def get(self, url: str, *, headers: dict[str, str], timeout: float) -> FakeResponse:
        del timeout
        self.calls.append((url, dict(headers)))
        return self.handler(url, dict(headers))

    async def close(self) -> None:
        self.closed = True


def _json_response(payload: Any, status: int = 200) -> FakeResponse:
    body = json.dumps(payload).encode()
    return FakeResponse(status_code=status, _payload=payload, content=body)


def _client(handler: Callable[[str, dict[str, str]], FakeResponse]) -> GoldbetClient:
    session = FakeSession(handler=handler)
    # No rate-limit + no retry wait so tests stay fast.
    return GoldbetClient(session=session, min_interval_seconds=0.0, max_attempts=3)


class TestWarmupAndHeaders:
    @pytest.mark.asyncio
    async def test_sends_mandatory_headers_after_warmup(self) -> None:
        def handler(url: str, _headers: dict[str, str]) -> FakeResponse:
            if url == WARMUP_URL:
                return FakeResponse(status_code=200)
            return _json_response({"leo": [], "success": True})

        async with _client(handler) as client:
            await client.fetch_tournament_events(93)

        sess = _session(client)
        # First call is warmup; every subsequent call must carry X-* headers.
        assert sess.calls[0][0] == WARMUP_URL
        for url, headers in sess.calls[1:]:
            assert url.startswith(BASE_URL)
            for mandatory in ("X-Brand", "X-IdCanale", "X-AcceptConsent", "X-Verticale"):
                assert mandatory in headers, f"{mandatory} missing in call to {url}"

    @pytest.mark.asyncio
    async def test_warmup_runs_once(self) -> None:
        def handler(url: str, _headers: dict[str, str]) -> FakeResponse:
            if url == WARMUP_URL:
                return FakeResponse(status_code=200)
            return _json_response({"leo": [], "success": True})

        async with _client(handler) as client:
            await client.fetch_tournament_events(93)
            await client.fetch_tournament_events(95)
            await client.fetch_tournament_events(84)

        warmup_calls = [c for c in _session(client).calls if c[0] == WARMUP_URL]
        assert len(warmup_calls) == 1


class TestRetriesAndRefresh:
    @pytest.mark.asyncio
    async def test_retries_on_transient_errors(self) -> None:
        attempts = {"n": 0}

        def handler(url: str, _headers: dict[str, str]) -> FakeResponse:
            if url == WARMUP_URL:
                return FakeResponse(status_code=200)
            attempts["n"] += 1
            if attempts["n"] < 3:
                return FakeResponse(status_code=503)
            return _json_response({"leo": [{"ei": 1}], "success": True})

        async with _client(handler) as client:
            events = await client.fetch_tournament_events(93)

        assert events == [{"ei": 1}]
        assert attempts["n"] == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries_and_raises(self) -> None:
        def handler(url: str, _headers: dict[str, str]) -> FakeResponse:
            if url == WARMUP_URL:
                return FakeResponse(status_code=200)
            return FakeResponse(status_code=503)

        async with _client(handler) as client:
            with pytest.raises(GoldbetError):
                await client.fetch_tournament_events(93)

    @pytest.mark.asyncio
    async def test_403_triggers_cookie_refresh_and_retries_once(self) -> None:
        seen_after_refresh = {"value": False}
        state = {"warmups": 0, "api_calls": 0}

        def handler(url: str, _headers: dict[str, str]) -> FakeResponse:
            if url == WARMUP_URL:
                state["warmups"] += 1
                # Second warmup = refresh after 403
                if state["warmups"] == 2:
                    seen_after_refresh["value"] = True
                return FakeResponse(status_code=200)
            state["api_calls"] += 1
            if not seen_after_refresh["value"]:
                return FakeResponse(status_code=403)
            return _json_response({"leo": [{"ei": 42}], "success": True})

        async with _client(handler) as client:
            events = await client.fetch_tournament_events(93)

        assert events == [{"ei": 42}]
        assert state["warmups"] == 2
        # one failed 403 call + one success after refresh
        assert state["api_calls"] == 2

    @pytest.mark.asyncio
    async def test_non_retriable_4xx_raises(self) -> None:
        def handler(url: str, _headers: dict[str, str]) -> FakeResponse:
            if url == WARMUP_URL:
                return FakeResponse(status_code=200)
            return FakeResponse(status_code=404)

        async with _client(handler) as client:
            with pytest.raises(GoldbetError):
                await client.fetch_tournament_events(93)


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_waits_between_requests(self) -> None:
        def handler(url: str, _headers: dict[str, str]) -> FakeResponse:
            if url == WARMUP_URL:
                return FakeResponse(status_code=200)
            return _json_response({"leo": [], "success": True})

        client = GoldbetClient(
            session=FakeSession(handler=handler),
            min_interval_seconds=0.05,
            max_attempts=1,
        )
        async with client:
            start = time.monotonic()
            await client.fetch_tournament_events(93)
            await client.fetch_tournament_events(95)
            await client.fetch_tournament_events(84)
            elapsed = time.monotonic() - start

        # 1 warmup + 3 api calls = 4 calls; 3 intervals after the first call
        assert elapsed >= 3 * 0.05 - 0.02


class TestFetchEventMarkets:
    @pytest.mark.asyncio
    async def test_url_shape(self) -> None:
        seen: list[str] = []

        def handler(url: str, _headers: dict[str, str]) -> FakeResponse:
            if url == WARMUP_URL:
                return FakeResponse(status_code=200)
            seen.append(url)
            return _json_response({"leo": [], "lmtW": [], "success": True})

        async with _client(handler) as client:
            await client.fetch_event_markets(
                id_aams_tournament=21,
                id_tournament=93,
                id_aams_event="61061617",
                id_event=15408447,
                tab_id=0,
            )
        assert seen == [
            f"{BASE_URL}/api/sport/pregame/getDetailsEventAams/21/93/61061617/15408447/0/0"
        ]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _session(client: GoldbetClient) -> FakeSession:
    assert isinstance(client.session, FakeSession)
    return client.session


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


_KEEP_ASYNCIO = asyncio
