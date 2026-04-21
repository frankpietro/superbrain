"""Tests for the SMTP_SSL email channel.

``smtplib.SMTP_SSL`` is patched with a stub that records every call;
the EmailMessage built by the channel is captured verbatim so we can
assert on headers, recipient list, multipart structure and table
contents.
"""

from __future__ import annotations

from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path
from typing import Any, ClassVar

import pytest

from superbrain.alerts.channels.email import (
    EmailChannel,
    render_html,
    render_text,
)
from superbrain.alerts.config import AlertSettings
from superbrain.alerts.models import AlertRecord
from tests.alerts.conftest import make_match, make_value_bet


class _FakeSMTP:
    """Minimal stand-in for ``smtplib.SMTP_SSL`` used across tests.

    The class is both the context manager and the server; ``login`` and
    ``send_message`` record their arguments so tests can introspect.
    """

    instances: ClassVar[list[_FakeSMTP]] = []

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.login_args: tuple[str, str] | None = None
        self.sent_messages: list[EmailMessage] = []
        self.closed = False
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.closed = True

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, message: EmailMessage) -> None:
        self.sent_messages.append(message)


class _FailingSMTP(_FakeSMTP):
    def send_message(self, message: EmailMessage) -> None:
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def _reset_fake_smtp() -> Iterator[None]:
    _FakeSMTP.instances.clear()
    yield
    _FakeSMTP.instances.clear()


@pytest.fixture()
def patch_smtp(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSMTP]:
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSMTP)
    return _FakeSMTP


@pytest.fixture()
def patch_failing_smtp(monkeypatch: pytest.MonkeyPatch) -> type[_FailingSMTP]:
    monkeypatch.setattr("smtplib.SMTP_SSL", _FailingSMTP)
    return _FailingSMTP


def _alerts(count: int = 2) -> list[AlertRecord]:
    bets = [
        make_value_bet(
            fixture=make_match(home=f"H{i}", away=f"A{i}"),
            selection="OVER",
            odds=1.90 + 0.01 * i,
            edge=0.08 + 0.01 * i,
        )
        for i in range(count)
    ]
    return [AlertRecord.from_value_bet(b) for b in bets]


@pytest.mark.asyncio
async def test_send_builds_multipart_message_with_correct_headers(
    patch_smtp: type[_FakeSMTP],
) -> None:
    channel = EmailChannel(
        host="smtp.example.com",
        port=465,
        username="user",
        password="pw",
        sender="superbrain@example.com",
        recipients=("a@example.com", "b@example.com"),
    )
    alerts = _alerts(count=2)

    results = await channel.send(alerts)

    assert len(results) == len(alerts)
    assert all(r.status == "sent" for r in results)

    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.host == "smtp.example.com"
    assert smtp.port == 465
    assert smtp.login_args == ("user", "pw")
    assert smtp.closed is True
    assert len(smtp.sent_messages) == 1

    message = smtp.sent_messages[0]
    assert message["From"] == "superbrain@example.com"
    assert message["To"] == "a@example.com, b@example.com"
    assert "[superbrain]" in str(message["Subject"])
    assert "value bets" in str(message["Subject"])

    parts = message.iter_parts()
    subtypes: list[str] = []
    contents: list[str] = []
    for part in parts:
        subtypes.append(part.get_content_subtype())
        payload = part.get_content()
        contents.append(payload if isinstance(payload, str) else payload.decode())
    assert "plain" in subtypes
    assert "html" in subtypes

    plain_body = next(c for c, st in zip(contents, subtypes, strict=True) if st == "plain")
    html_body = next(c for c, st in zip(contents, subtypes, strict=True) if st == "html")
    for alert in alerts:
        assert alert.home_team in plain_body
        assert alert.home_team in html_body
    assert "<table" in html_body
    assert html_body.count("<tr>") >= len(alerts)


@pytest.mark.asyncio
async def test_single_alert_subject_uses_match_label(
    patch_smtp: type[_FakeSMTP],
) -> None:
    channel = EmailChannel(
        host="smtp.example.com",
        port=465,
        username="u",
        password="p",
        sender="from@example.com",
        recipients=("to@example.com",),
    )
    alerts = _alerts(count=1)
    await channel.send(alerts)
    message = _FakeSMTP.instances[0].sent_messages[0]
    subject = str(message["Subject"])
    assert alerts[0].home_team in subject
    assert alerts[0].away_team in subject


@pytest.mark.asyncio
async def test_empty_input_sends_nothing(patch_smtp: type[_FakeSMTP]) -> None:
    channel = EmailChannel(
        host="smtp.example.com",
        port=465,
        username="u",
        password="p",
        sender="from@example.com",
        recipients=("to@example.com",),
    )
    results = await channel.send([])
    assert results == []
    assert _FakeSMTP.instances == []


@pytest.mark.asyncio
async def test_smtp_failure_marks_all_alerts_failed(
    patch_failing_smtp: type[_FailingSMTP],
) -> None:
    channel = EmailChannel(
        host="smtp.example.com",
        port=465,
        username="u",
        password="p",
        sender="from@example.com",
        recipients=("to@example.com",),
    )
    alerts = _alerts(count=3)
    results = await channel.send(alerts)
    assert len(results) == 3
    assert all(r.status == "failed" for r in results)
    assert all("RuntimeError" in r.error for r in results)


def test_render_text_lists_every_alert() -> None:
    alerts = _alerts(count=2)
    text = render_text(alerts)
    for alert in alerts:
        assert alert.home_team in text
        assert alert.selection in text
    assert "2 value bet(s)" in text


def test_render_html_table_has_row_per_alert() -> None:
    alerts = _alerts(count=3)
    html_body = render_html(alerts)
    assert html_body.count("<tr>") == len(alerts) + 1  # +1 for <thead>
    assert "Edge" in html_body


def test_from_settings_returns_none_when_unset(tmp_path: Path) -> None:
    settings = AlertSettings(SUPERBRAIN_ALERT_SINK_PATH=tmp_path / "sink.parquet")
    assert EmailChannel.from_settings(settings) is None


def test_from_settings_requires_full_config(tmp_path: Path) -> None:
    settings = AlertSettings(
        SUPERBRAIN_SMTP_HOST="smtp.example.com",
        SUPERBRAIN_SMTP_USER="u",
        SUPERBRAIN_SMTP_PASSWORD="p",
        SUPERBRAIN_SMTP_FROM="from@example.com",
        SUPERBRAIN_ALERT_EMAIL_RECIPIENTS=("to@example.com",),
        SUPERBRAIN_ALERT_SINK_PATH=tmp_path / "sink.parquet",
    )
    channel = EmailChannel.from_settings(settings)
    assert channel is not None
    assert channel.name == "email"
