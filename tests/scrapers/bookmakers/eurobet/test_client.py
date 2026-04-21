"""Unit tests for :class:`EurobetClient`.

``httpx`` calls are mocked with ``respx``; ``curl_cffi`` is swapped out
by monkey-patching :func:`_ensure_cffi_session` with a minimal async
double that records requests and returns pre-canned responses.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import respx

from superbrain.scrapers.bookmakers.eurobet import client as eurobet_client
from superbrain.scrapers.bookmakers.eurobet.client import (
    CFFI_DEFAULT_HEADERS,
    EUROBET_BASE,
    PUBLIC_DEFAULT_HEADERS,
    EurobetClient,
    EurobetError,
)

# ---------------------------------------------------------------------------
# curl_cffi fake adapter
# ---------------------------------------------------------------------------


@dataclass
class _FakeCFFIResponse:
    status_code: int
    _body: bytes
    _text: str

    def json(self) -> Any:
        return json.loads(self._body)

    @property
    def text(self) -> str:
        return self._text


class _FakeCFFISession:
    def __init__(self, responses: list[_FakeCFFIResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        impersonate: str | None = None,
    ) -> _FakeCFFIResponse:
        self.requests.append(
            {
                "url": url,
                "params": dict(params) if params else None,
                "headers": dict(headers) if headers else None,
                "impersonate": impersonate,
            }
        )
        if not self._responses:
            raise AssertionError("no more canned responses")
        return self._responses.pop(0)

    async def close(self) -> None:
        return None


def _ok(body: dict[str, Any]) -> _FakeCFFIResponse:
    raw = json.dumps(body).encode()
    return _FakeCFFIResponse(200, raw, raw.decode())


def _err(status: int, text: str) -> _FakeCFFIResponse:
    return _FakeCFFIResponse(status, text.encode(), text)


@pytest.fixture
def cffi_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[list[_FakeCFFIResponse]], _FakeCFFISession]:
    """Return a helper that installs a pre-seeded fake curl_cffi session."""

    sessions: list[_FakeCFFISession] = []

    def install(responses: list[_FakeCFFIResponse]) -> _FakeCFFISession:
        sess = _FakeCFFISession(responses)
        sessions.append(sess)

        async def _ensure(self: EurobetClient) -> _FakeCFFISession:
            return sess

        monkeypatch.setattr(EurobetClient, "_ensure_cffi_session", _ensure)
        return sess

    return install


# ---------------------------------------------------------------------------
# Public (httpx) endpoints
# ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_top_disciplines_url_and_headers() -> None:
    url = (
        f"{EUROBET_BASE}/prematch-homepage-service/api/v2/sport-schedule"
        f"/services/top-disciplines/1/calcio"
    )
    route = respx.get(url).mock(return_value=httpx.Response(200, json={"code": 1, "result": []}))
    async with EurobetClient(min_interval_s=0.0) as client:
        payload = await client.fetch_top_disciplines()
    assert payload == {"code": 1, "result": []}
    assert route.called
    req = route.calls.last.request
    for k, v in PUBLIC_DEFAULT_HEADERS.items():
        assert req.headers.get(k) == v, k


@respx.mock
async def test_fetch_sport_list_url() -> None:
    url = f"{EUROBET_BASE}/prematch-menu-service/api/v2/sport-schedule/services/sport-list/calcio"
    route = respx.get(url).mock(return_value=httpx.Response(200, json={"code": 1, "result": {}}))
    async with EurobetClient(min_interval_s=0.0) as client:
        payload = await client.fetch_sport_list()
    assert payload == {"code": 1, "result": {}}
    assert route.called


@respx.mock
async def test_fetch_meeting_next_url() -> None:
    url = f"{EUROBET_BASE}/_next/data/abc123/it/scommesse/calcio/it-serie-a.json"
    route = respx.get(url).mock(return_value=httpx.Response(200, json={"pageProps": {}}))
    async with EurobetClient(min_interval_s=0.0) as client:
        payload = await client.fetch_meeting_next(
            build_id="abc123",
            discipline_alias="calcio",
            meeting_slug="it-serie-a",
        )
    assert payload == {"pageProps": {}}
    assert route.called


@respx.mock
async def test_fetch_landing_build_id_extracts_from_next_data() -> None:
    html = (
        "<html><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"buildId":"deadbeef","props":{}}</script>'
        "</body></html>"
    )
    respx.get(f"{EUROBET_BASE}/it/scommesse/calcio").mock(
        return_value=httpx.Response(200, text=html)
    )
    async with EurobetClient(min_interval_s=0.0) as client:
        build_id = await client.fetch_landing_build_id()
    assert build_id == "deadbeef"


@respx.mock
async def test_retries_then_succeeds_on_503() -> None:
    url = (
        f"{EUROBET_BASE}/prematch-homepage-service/api/v2/sport-schedule"
        f"/services/top-disciplines/1/calcio"
    )
    respx.get(url).mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"code": 1, "result": []}),
        ]
    )
    async with EurobetClient(min_interval_s=0.0, max_attempts=3) as client:
        payload = await client.fetch_top_disciplines()
    assert payload == {"code": 1, "result": []}


@respx.mock
async def test_retries_exhausted_raise() -> None:
    url = (
        f"{EUROBET_BASE}/prematch-homepage-service/api/v2/sport-schedule"
        f"/services/top-disciplines/1/calcio"
    )
    respx.get(url).mock(return_value=httpx.Response(502, text="bad gateway"))
    async with EurobetClient(min_interval_s=0.0, max_attempts=2) as client:
        with pytest.raises(eurobet_client._RetryableHTTPError):
            await client.fetch_top_disciplines()


@respx.mock
async def test_400_raises_eurobet_error_without_retry() -> None:
    url = (
        f"{EUROBET_BASE}/prematch-homepage-service/api/v2/sport-schedule"
        f"/services/top-disciplines/1/calcio"
    )
    route = respx.get(url).mock(return_value=httpx.Response(400, text="bad"))
    async with EurobetClient(min_interval_s=0.0, max_attempts=3) as client:
        with pytest.raises(EurobetError):
            await client.fetch_top_disciplines()
    assert route.call_count == 1


# ---------------------------------------------------------------------------
# Cloudflare-gated (curl_cffi) endpoints
# ---------------------------------------------------------------------------


async def test_fetch_event_routes_through_cffi_with_tenant_headers(
    cffi_session_factory: Callable[[list[_FakeCFFIResponse]], _FakeCFFISession],
) -> None:
    sess = cffi_session_factory([_ok({"code": 1, "result": {"betGroupList": []}})])
    async with EurobetClient(min_interval_s=0.0) as client:
        payload = await client.fetch_event(
            discipline_alias="calcio",
            meeting_slug="it-serie-a",
            event_slug="napoli-cremonese-202604242045",
        )
    assert payload["code"] == 1
    assert len(sess.requests) == 1
    req = sess.requests[0]
    assert (
        req["url"] == f"{EUROBET_BASE}/detail-service/sport-schedule/services/event/"
        f"calcio/it-serie-a/napoli-cremonese-202604242045"
    )
    assert req["impersonate"] == "chrome124"
    assert req["headers"]["X-EB-MarketId"] == CFFI_DEFAULT_HEADERS["X-EB-MarketId"]
    assert req["headers"]["X-EB-PlatformId"] == CFFI_DEFAULT_HEADERS["X-EB-PlatformId"]
    assert req["params"] == {"prematch": 1, "live": 0}


async def test_fetch_event_with_group_alias_appends_path(
    cffi_session_factory: Callable[[list[_FakeCFFIResponse]], _FakeCFFISession],
) -> None:
    sess = cffi_session_factory([_ok({"code": 1, "result": {}})])
    async with EurobetClient(min_interval_s=0.0) as client:
        await client.fetch_event(
            discipline_alias="calcio",
            meeting_slug="it-serie-a",
            event_slug="x-y-202604242045",
            group_alias="tutte",
        )
    assert sess.requests[0]["url"].endswith("/x-y-202604242045/tutte")


async def test_fetch_meeting_uses_cffi(
    cffi_session_factory: Callable[[list[_FakeCFFIResponse]], _FakeCFFISession],
) -> None:
    sess = cffi_session_factory([_ok({"code": 1, "result": {"dataGroupList": []}})])
    async with EurobetClient(min_interval_s=0.0) as client:
        payload = await client.fetch_meeting(
            discipline_alias="calcio",
            meeting_slug="it-serie-a",
        )
    assert payload["code"] == 1
    assert "detail-service/sport-schedule/services/meeting" in sess.requests[0]["url"]


async def test_cffi_app_level_error_raises(
    cffi_session_factory: Callable[[list[_FakeCFFIResponse]], _FakeCFFISession],
) -> None:
    cffi_session_factory([_ok({"code": -99, "description": "validation error", "result": []})])
    async with EurobetClient(min_interval_s=0.0) as client:
        with pytest.raises(EurobetError) as exc:
            await client.fetch_event(
                discipline_alias="calcio",
                meeting_slug="it-serie-a",
                event_slug="x-y-1",
            )
    assert exc.value.code == -99


async def test_cffi_retries_on_503(
    cffi_session_factory: Callable[[list[_FakeCFFIResponse]], _FakeCFFISession],
) -> None:
    cffi_session_factory([_err(503, "busy"), _ok({"code": 1, "result": {"betGroupList": []}})])
    async with EurobetClient(min_interval_s=0.0, max_attempts=3) as client:
        payload = await client.fetch_event(
            discipline_alias="calcio",
            meeting_slug="it-serie-a",
            event_slug="x-y-1",
        )
    assert payload["code"] == 1
