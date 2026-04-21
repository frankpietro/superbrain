"""End-to-end :class:`AlertDispatcher` tests against stub channels.

We never hit the network: two in-memory ``Channel`` stubs stand in for
Telegram + email. The tests cover (a) idempotency — dispatching the
same value bets twice alerts each exactly once — and (b) resilience —
one channel raising does not suppress the others.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from superbrain.alerts.config import AlertSettings
from superbrain.alerts.dispatcher import AlertDispatcher, AlertRunReport
from superbrain.alerts.models import AlertRecord, ChannelResult
from superbrain.alerts.sink import AlertSink
from tests.alerts.conftest import make_match, make_value_bet


class StubChannel:
    """Records every batch it receives and returns synthetic results."""

    def __init__(
        self,
        name: str,
        *,
        status: str = "sent",
        raise_exc: BaseException | None = None,
    ) -> None:
        self.name = name
        self._status = status
        self._raise = raise_exc
        self.batches: list[list[AlertRecord]] = []

    async def send(self, alerts: Sequence[AlertRecord]) -> list[ChannelResult]:
        self.batches.append(list(alerts))
        if self._raise is not None:
            raise self._raise
        now = datetime.now(tz=UTC)
        return [
            ChannelResult(
                alert_id=alert.alert_id,
                channel=self.name,
                status=self._status,
                sent_at=now,
                error="" if self._status == "sent" else "stub-error",
            )
            for alert in alerts
        ]


def _build_dispatcher(
    settings: AlertSettings, *, channels: Sequence[StubChannel]
) -> AlertDispatcher:
    sink = AlertSink(settings.alert_sink_path)
    return AlertDispatcher(settings=settings, channels=channels, sink=sink)


@pytest.mark.asyncio
async def test_happy_path_dispatches_to_every_channel(
    default_settings: AlertSettings,
) -> None:
    telegram = StubChannel("telegram")
    email = StubChannel("email")
    dispatcher = _build_dispatcher(default_settings, channels=[telegram, email])
    bets = [
        make_value_bet(
            fixture=make_match(home=f"H{i}", away=f"A{i}"),
            edge=0.10 + 0.01 * i,
            odds=1.90 + i * 0.01,
        )
        for i in range(3)
    ]

    report = await dispatcher.dispatch(bets)

    assert isinstance(report, AlertRunReport)
    assert report.considered == 3
    assert report.admitted == 3
    assert report.sent == 3
    assert report.failed == 0
    assert len(telegram.batches[0]) == 3
    assert len(email.batches[0]) == 3


@pytest.mark.asyncio
async def test_idempotency_second_dispatch_alerts_nothing_new(
    default_settings: AlertSettings,
) -> None:
    telegram = StubChannel("telegram")
    email = StubChannel("email")
    dispatcher = _build_dispatcher(default_settings, channels=[telegram, email])
    bets = [
        make_value_bet(
            fixture=make_match(home=f"H{i}", away=f"A{i}"),
            edge=0.08,
            odds=1.90 + 0.01 * i,
        )
        for i in range(4)
    ]

    first = await dispatcher.dispatch(bets)
    assert first.sent == 4
    assert len(telegram.batches) == 1
    assert len(telegram.batches[0]) == 4

    second = await dispatcher.dispatch(bets)
    assert second.considered == 4
    assert second.admitted == 0
    assert second.sent == 0
    # No second batch was pushed to any channel because the policy
    # dropped every alert against the sink.
    assert len(telegram.batches) == 1
    assert len(email.batches) == 1


@pytest.mark.asyncio
async def test_one_channel_failing_does_not_suppress_the_other(
    default_settings: AlertSettings,
) -> None:
    failing = StubChannel("telegram", raise_exc=RuntimeError("network unreachable"))
    ok = StubChannel("email")
    dispatcher = _build_dispatcher(default_settings, channels=[failing, ok])
    bets = [
        make_value_bet(
            fixture=make_match(home=f"H{i}", away=f"A{i}"),
            edge=0.08,
            odds=1.90 + 0.01 * i,
        )
        for i in range(2)
    ]

    report = await dispatcher.dispatch(bets)

    assert report.admitted == 2
    # Every alert has at least one successful channel -> counted as sent.
    assert report.sent == 2
    assert report.failed == 0
    assert report.channel_status["telegram"] == {"failed": 2}
    assert report.channel_status["email"] == {"sent": 2}
    # The working channel still received the batch.
    assert len(ok.batches[0]) == 2


@pytest.mark.asyncio
async def test_failed_channel_does_not_block_retry_on_next_dispatch(
    default_settings: AlertSettings,
) -> None:
    failing = StubChannel("telegram", status="failed")
    failing_email = StubChannel("email", status="failed")
    dispatcher = _build_dispatcher(default_settings, channels=[failing, failing_email])
    bets = [make_value_bet()]

    first = await dispatcher.dispatch(bets)
    assert first.admitted == 1
    assert first.sent == 0
    assert first.failed == 1

    # Because no channel succeeded, the alert id is NOT in the "alerted"
    # set; the second dispatch must try again.
    second = await dispatcher.dispatch(bets)
    assert second.admitted == 1
    assert second.sent == 0
    assert len(failing.batches) == 2


@pytest.mark.asyncio
async def test_empty_input_short_circuits(default_settings: AlertSettings) -> None:
    telegram = StubChannel("telegram")
    dispatcher = _build_dispatcher(default_settings, channels=[telegram])
    report = await dispatcher.dispatch([])
    assert report.considered == 0
    assert report.admitted == 0
    assert report.sent == 0
    assert telegram.batches == []


@pytest.mark.asyncio
async def test_policy_rejections_do_not_reach_channels(
    default_settings: AlertSettings,
) -> None:
    telegram = StubChannel("telegram")
    dispatcher = _build_dispatcher(default_settings, channels=[telegram])
    bets = [
        make_value_bet(edge=0.10, probability=0.50),  # admitted
        make_value_bet(edge=0.02, probability=0.50, selection="UNDER"),  # rejected
    ]
    report = await dispatcher.dispatch(bets)
    assert report.considered == 2
    assert report.admitted == 1
    assert len(telegram.batches[0]) == 1


@pytest.mark.asyncio
async def test_channel_returning_fewer_results_is_padded(
    default_settings: AlertSettings,
) -> None:
    class ShortChannel:
        name = "short"

        def __init__(self) -> None:
            self.batches: list[list[AlertRecord]] = []

        async def send(self, alerts: Sequence[AlertRecord]) -> list[ChannelResult]:
            self.batches.append(list(alerts))
            return []  # misbehaving channel

    channel = ShortChannel()
    dispatcher = _build_dispatcher(default_settings, channels=[channel])  # type: ignore[list-item]
    bets = [make_value_bet()]
    report = await dispatcher.dispatch(bets)
    assert report.admitted == 1
    # Dispatcher padded the missing result -> status "failed".
    assert report.sent == 0
    assert report.failed == 1


@pytest.mark.asyncio
async def test_from_settings_skips_disabled_channels(tmp_path: Any) -> None:
    settings = AlertSettings(
        SUPERBRAIN_ALERT_SINK_PATH=tmp_path / "sink.parquet",
    )
    dispatcher = AlertDispatcher.from_settings(settings)
    assert dispatcher.channels == ()
