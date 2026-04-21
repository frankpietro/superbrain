"""Unit tests for ``SisalClient`` (respx-mocked)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from superbrain.scrapers.bookmakers.sisal.client import (
    SISAL_DEFAULT_HEADERS,
    SISAL_PREMATCH_BASE,
    SisalClient,
    SisalError,
)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_tree_sends_expected_headers() -> None:
    route = respx.get(f"{SISAL_PREMATCH_BASE}/alberaturaPrematch").mock(
        return_value=httpx.Response(200, json={"disciplinaMap": {}})
    )
    async with SisalClient(min_interval_s=0.0) as client:
        payload = await client.fetch_tree()
    assert payload == {"disciplinaMap": {}}
    assert route.called
    request = route.calls.last.request
    for k, v in SISAL_DEFAULT_HEADERS.items():
        assert request.headers.get(k) == v, k


@pytest.mark.asyncio
@respx.mock
async def test_fetch_events_url_and_response() -> None:
    route = respx.get(f"{SISAL_PREMATCH_BASE}/v1/schedaManifestazione/0/1-209").mock(
        return_value=httpx.Response(200, json={"avvenimentoFeList": []})
    )
    async with SisalClient(min_interval_s=0.0) as client:
        payload = await client.fetch_events("1-209")
    assert payload == {"avvenimentoFeList": []}
    request = route.calls.last.request
    assert request.url.params.get("offerId") == "0"
    assert request.url.params.get("metaTplEnabled") == "true"
    assert request.url.params.get("deep") == "true"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_event_markets_url() -> None:
    route = respx.get(f"{SISAL_PREMATCH_BASE}/schedaAvvenimento/36171-19").mock(
        return_value=httpx.Response(200, json={"avvenimentoFe": {}, "scommessaMap": {}})
    )
    async with SisalClient(min_interval_s=0.0) as client:
        payload = await client.fetch_event_markets("36171-19")
    assert "scommessaMap" in payload
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_retries_on_503_then_succeeds() -> None:
    url = f"{SISAL_PREMATCH_BASE}/alberaturaPrematch"
    respx.get(url).mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"disciplinaMap": {}}),
        ]
    )
    async with SisalClient(min_interval_s=0.0, max_attempts=3) as client:
        payload = await client.fetch_tree()
    assert payload == {"disciplinaMap": {}}


@pytest.mark.asyncio
@respx.mock
async def test_retries_exhausted_raise_sisal_error() -> None:
    url = f"{SISAL_PREMATCH_BASE}/alberaturaPrematch"
    respx.get(url).mock(return_value=httpx.Response(503, text="busy"))
    async with SisalClient(min_interval_s=0.0, max_attempts=2) as client:
        with pytest.raises(SisalError) as excinfo:
            await client.fetch_tree()
    assert excinfo.value.status == 503


@pytest.mark.asyncio
@respx.mock
async def test_non_429_client_error_is_not_retried() -> None:
    url = f"{SISAL_PREMATCH_BASE}/alberaturaPrematch"
    route = respx.get(url).mock(return_value=httpx.Response(404, text="not found"))
    async with SisalClient(min_interval_s=0.0, max_attempts=5) as client:
        with pytest.raises(SisalError) as excinfo:
            await client.fetch_tree()
    assert excinfo.value.status == 404
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_429_is_retried_like_5xx() -> None:
    url = f"{SISAL_PREMATCH_BASE}/alberaturaPrematch"
    respx.get(url).mock(
        side_effect=[
            httpx.Response(429, text="too fast"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with SisalClient(min_interval_s=0.0, max_attempts=3) as client:
        payload = await client.fetch_tree()
    assert payload == {"ok": True}


@pytest.mark.asyncio
@respx.mock
async def test_semaphore_spaces_requests() -> None:
    url = f"{SISAL_PREMATCH_BASE}/alberaturaPrematch"
    respx.get(url).mock(return_value=httpx.Response(200, json={"ok": True}))
    # Use a non-trivial interval but still fast enough to run in tests.
    interval = 0.05
    async with SisalClient(min_interval_s=interval, max_attempts=1) as client:
        t0 = asyncio.get_event_loop().time()
        await asyncio.gather(*[client.fetch_tree() for _ in range(3)])
        elapsed = asyncio.get_event_loop().time() - t0
    # Three calls, pairwise spacing `interval` means at least 2x interval wait.
    assert elapsed >= 2 * interval - 0.005


@pytest.mark.asyncio
@respx.mock
async def test_non_json_body_raises_sisal_error() -> None:
    url = f"{SISAL_PREMATCH_BASE}/alberaturaPrematch"
    respx.get(url).mock(return_value=httpx.Response(200, text="<html>oops</html>"))
    async with SisalClient(min_interval_s=0.0, max_attempts=1) as client:
        with pytest.raises(SisalError):
            await client.fetch_tree()
