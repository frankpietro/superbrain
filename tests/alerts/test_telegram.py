"""Tests for the Telegram delivery channel.

Every HTTP call is intercepted by ``respx``; no real request ever leaves
the test runner. We assert on (a) the happy-path payload shape Telegram
expects, (b) the 429 backoff + ``retry_after`` honouring, and (c) the
behaviour when the API returns a malformed body.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from superbrain.alerts.channels.telegram import (
    TELEGRAM_API_BASE,
    TelegramChannel,
    render_message,
)
from superbrain.alerts.config import AlertSettings
from superbrain.alerts.models import AlertRecord
from tests.alerts.conftest import make_value_bet

BOT_TOKEN = "test-bot-token"


def _alert() -> AlertRecord:
    vb = make_value_bet(edge=0.12, probability=0.6, odds=2.0)
    return AlertRecord.from_value_bet(vb)


class _RecordingSleep:
    """Coroutine drop-in that records every delay without actually sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.calls.append(float(delay))


@pytest.fixture()
def recording_sleep() -> _RecordingSleep:
    return _RecordingSleep()


@pytest.fixture()
def channel_factory(recording_sleep: _RecordingSleep) -> Any:
    """Build a TelegramChannel bound to a respx-mocked transport."""

    def _factory(chat_ids: tuple[str, ...] = ("12345",)) -> TelegramChannel:
        return TelegramChannel(
            bot_token=BOT_TOKEN,
            chat_ids=chat_ids,
            client=None,
            concurrency=1,
            max_attempts=3,
            backoff_base=0.1,
            sleep=recording_sleep,
        )

    return _factory


@pytest.mark.asyncio
async def test_happy_path_payload_shape(channel_factory: Any) -> None:
    alert = _alert()
    channel = channel_factory(chat_ids=("12345",))

    with respx.mock(base_url=TELEGRAM_API_BASE) as mock:
        route = mock.post(f"/bot{BOT_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})
        )
        results = await channel.send([alert])

    assert [r.status for r in results] == ["sent"]
    assert route.call_count == 1

    payload = json.loads(route.calls.last.request.content)
    assert payload["chat_id"] == "12345"
    assert payload["parse_mode"] == "HTML"
    assert payload["disable_web_page_preview"] is True
    body = payload["text"]
    assert alert.home_team in body
    assert alert.away_team in body
    assert alert.selection in body
    assert alert.bookmaker in body
    assert "Edge" in body


@pytest.mark.asyncio
async def test_429_honours_retry_after(
    channel_factory: Any, recording_sleep: _RecordingSleep
) -> None:
    alert = _alert()
    channel = channel_factory()

    with respx.mock(base_url=TELEGRAM_API_BASE) as mock:
        responses = [
            httpx.Response(
                429,
                json={
                    "ok": False,
                    "error_code": 429,
                    "description": "rate limited",
                    "parameters": {"retry_after": 7},
                },
            ),
            httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}),
        ]
        mock.post(f"/bot{BOT_TOKEN}/sendMessage").mock(side_effect=responses)
        results = await channel.send([alert])

    assert [r.status for r in results] == ["sent"]
    assert 7.0 in recording_sleep.calls


@pytest.mark.asyncio
async def test_429_exhausts_attempts_sets_failed(
    channel_factory: Any,
) -> None:
    alert = _alert()
    channel = channel_factory()

    with respx.mock(base_url=TELEGRAM_API_BASE) as mock:
        mock.post(f"/bot{BOT_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(
                429,
                json={
                    "ok": False,
                    "error_code": 429,
                    "parameters": {"retry_after": 1},
                    "description": "flood",
                },
            )
        )
        results = await channel.send([alert])

    assert len(results) == 1
    assert results[0].status == "failed"
    assert "429" in results[0].error


@pytest.mark.asyncio
async def test_malformed_body_is_treated_as_failure(channel_factory: Any) -> None:
    alert = _alert()
    channel = channel_factory()

    with respx.mock(base_url=TELEGRAM_API_BASE) as mock:
        mock.post(f"/bot{BOT_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, content=b"not-json")
        )
        results = await channel.send([alert])

    assert len(results) == 1
    assert results[0].status == "failed"
    assert "malformed" in results[0].error.lower()


@pytest.mark.asyncio
async def test_api_ok_false_is_failure(channel_factory: Any) -> None:
    alert = _alert()
    channel = channel_factory()

    with respx.mock(base_url=TELEGRAM_API_BASE) as mock:
        mock.post(f"/bot{BOT_TOKEN}/sendMessage").mock(
            return_value=httpx.Response(
                200,
                json={"ok": False, "error_code": 400, "description": "chat not found"},
            )
        )
        results = await channel.send([alert])

    assert results[0].status == "failed"
    assert "chat not found" in results[0].error


@pytest.mark.asyncio
async def test_multiple_chat_ids_partial_success(
    channel_factory: Any,
) -> None:
    alert = _alert()
    channel = channel_factory(chat_ids=("111", "222"))

    with respx.mock(base_url=TELEGRAM_API_BASE) as mock:

        def _dispatch(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            if payload["chat_id"] == "111":
                return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
            return httpx.Response(200, json={"ok": False, "description": "chat not found"})

        mock.post(f"/bot{BOT_TOKEN}/sendMessage").mock(side_effect=_dispatch)
        results = await channel.send([alert])

    assert results[0].status == "partial"
    assert "chat not found" in results[0].error


def test_render_message_escapes_html_meta_chars() -> None:
    vb = make_value_bet()
    alert = AlertRecord.from_value_bet(vb)
    alert_with_meta = dataclasses.replace(alert, bookmaker="<b>injected</b>", home_team="A & B")
    body = render_message(alert_with_meta)
    assert "<b>injected</b>" not in body
    assert "&lt;b&gt;injected&lt;/b&gt;" in body
    assert "A &amp; B" in body


def test_from_settings_returns_none_when_disabled(tmp_path: Path) -> None:
    settings = AlertSettings(SUPERBRAIN_ALERT_SINK_PATH=tmp_path / "sink.parquet")
    assert TelegramChannel.from_settings(settings) is None


def test_from_settings_returns_channel_when_enabled(tmp_path: Path) -> None:
    settings = AlertSettings(
        SUPERBRAIN_TELEGRAM_BOT_TOKEN="abc",
        SUPERBRAIN_TELEGRAM_CHAT_IDS=("1", "2"),
        SUPERBRAIN_ALERT_SINK_PATH=tmp_path / "sink.parquet",
    )
    channel = TelegramChannel.from_settings(settings)
    assert channel is not None
    assert channel.name == "telegram"
