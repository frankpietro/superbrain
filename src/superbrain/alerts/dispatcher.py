"""High-level orchestration: policy → channels → sink.

The dispatcher owns the entire sweep lifecycle:

1. Load alert ids sent within the dedup window from
   :class:`~superbrain.alerts.sink.AlertSink`.
2. Run the input ``value_bets`` through :class:`AlertPolicy`, collecting
   admitted :class:`AlertRecord` objects.
3. Fan out across every enabled channel **concurrently** (per the brief —
   one alert gets hit by every channel in parallel). Within a channel,
   alerts are processed sequentially so we don't exceed provider rate
   limits.
4. Persist every ``(alert, channel_result)`` pair to the sink.
5. Return a structured :class:`AlertRunReport`.

A channel raising is treated as a catastrophic failure for that channel
only: the other channels' results are preserved, and every alert still
gets a recorded :class:`ChannelResult` (``status="failed"``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from superbrain.alerts.channels.email import EmailChannel
from superbrain.alerts.channels.telegram import TelegramChannel
from superbrain.alerts.config import AlertSettings
from superbrain.alerts.models import AlertOutcome, AlertRecord, ChannelResult
from superbrain.alerts.policy import AlertPolicy
from superbrain.alerts.sink import AlertSink

if TYPE_CHECKING:
    from superbrain.alerts.channels.base import Channel
    from superbrain.engine.pipeline import ValueBet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertRunReport:
    """Summary of one :meth:`AlertDispatcher.dispatch` call.

    :ivar considered: number of input value bets evaluated by the policy.
    :ivar admitted: number of alerts that passed the policy and were
        attempted.
    :ivar sent: number of alerts with at least one successful channel.
    :ivar failed: number of alerts where no channel succeeded.
    :ivar channel_status: ``{channel_name: {status: count}}`` rollup.
    :ivar outcomes: full per-alert outcome list (record + per-channel
        results). Empty when the dispatcher short-circuited.
    :ivar started_at: UTC timestamp the sweep started.
    :ivar finished_at: UTC timestamp the sweep finished.
    """

    considered: int
    admitted: int
    sent: int
    failed: int
    channel_status: dict[str, dict[str, int]] = field(default_factory=dict)
    outcomes: tuple[AlertOutcome, ...] = ()
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    finished_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def summary(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dict (for logging / CLI output)."""
        return {
            "considered": self.considered,
            "admitted": self.admitted,
            "sent": self.sent,
            "failed": self.failed,
            "channel_status": self.channel_status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }


class AlertDispatcher:
    """Policy + channels + sink wired together.

    :param settings: env-driven configuration.
    :param channels: ordered list of delivery channels (typically
        Telegram + email).
    :param sink: parquet sink used for dedup and persistence.
    :param policy_factory: callable that returns a fresh
        :class:`AlertPolicy` given settings and the dedup-window seed.
    :param now: injectable clock, for deterministic tests.
    """

    def __init__(
        self,
        *,
        settings: AlertSettings,
        channels: Sequence[Channel],
        sink: AlertSink,
        policy_factory: Any = AlertPolicy,
        now: Any = None,
    ) -> None:
        self._settings = settings
        self._channels = tuple(channels)
        self._sink = sink
        self._policy_factory = policy_factory
        self._now = now if now is not None else _utcnow

    @classmethod
    def from_settings(
        cls,
        settings: AlertSettings,
        *,
        sink: AlertSink | None = None,
        channels: Sequence[Channel] | None = None,
    ) -> AlertDispatcher:
        """Build a dispatcher from env-derived settings.

        Channels whose credentials are missing are transparently
        skipped; tests inject their own stub channels via the
        ``channels`` override.
        """
        if channels is None:
            built: list[Channel] = []
            telegram = TelegramChannel.from_settings(settings)
            if telegram is not None:
                built.append(telegram)
            email = EmailChannel.from_settings(settings)
            if email is not None:
                built.append(email)
            channels = built
        if sink is None:
            sink = AlertSink(settings.alert_sink_path)
        return cls(settings=settings, channels=channels, sink=sink)

    @property
    def channels(self) -> tuple[Channel, ...]:
        return self._channels

    async def dispatch(self, value_bets: Sequence[ValueBet]) -> AlertRunReport:
        """Run one alert sweep end-to-end.

        :param value_bets: engine-produced value bets for the sweep.
        :return: :class:`AlertRunReport` with admission + per-channel stats.
        """
        started = self._now()
        considered = len(value_bets)
        logger.info("alerts.dispatch considered=%d", considered)

        since = started - timedelta(hours=self._settings.alert_dedup_hours)
        previous_ids = self._sink.load_alerted_ids(since=since)
        policy = self._policy_factory(self._settings, previous_ids)
        admitted = policy.filter(value_bets)
        logger.info(
            "alerts.dispatch admitted=%d suppressed=%d",
            len(admitted),
            considered - len(admitted),
        )

        if not admitted or not self._channels:
            return AlertRunReport(
                considered=considered,
                admitted=len(admitted),
                sent=0,
                failed=0,
                channel_status={},
                outcomes=(),
                started_at=started,
                finished_at=self._now(),
            )

        per_channel_results = await self._run_channels(admitted)
        outcomes = _zip_outcomes(admitted, per_channel_results)
        self._sink.record(outcomes)

        sent = sum(1 for o in outcomes if o.ok)
        failed = len(outcomes) - sent
        channel_status = _channel_status_rollup(per_channel_results)

        finished = self._now()
        report = AlertRunReport(
            considered=considered,
            admitted=len(admitted),
            sent=sent,
            failed=failed,
            channel_status=channel_status,
            outcomes=tuple(outcomes),
            started_at=started,
            finished_at=finished,
        )
        logger.info(
            "alerts.dispatch finished sent=%d failed=%d channels=%s",
            sent,
            failed,
            list(channel_status.keys()),
        )
        return report

    async def _run_channels(self, admitted: list[AlertRecord]) -> dict[str, list[ChannelResult]]:
        """Send ``admitted`` through every enabled channel in parallel.

        A raising channel becomes ``status="failed"`` for every alert.
        """

        async def _wrapped(channel: Channel) -> tuple[str, list[ChannelResult]]:
            try:
                results = await channel.send(admitted)
            except Exception as exc:
                logger.exception(
                    "alerts.channel %s raised — marking every alert failed",
                    channel.name,
                )
                now = self._now()
                results = [
                    ChannelResult(
                        alert_id=alert.alert_id,
                        channel=channel.name,
                        status="failed",
                        sent_at=now,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    for alert in admitted
                ]
            return channel.name, results

        pairs = await asyncio.gather(*(_wrapped(ch) for ch in self._channels))
        return dict(pairs)


def _zip_outcomes(
    admitted: Sequence[AlertRecord],
    per_channel: dict[str, list[ChannelResult]],
) -> list[AlertOutcome]:
    outcomes: list[AlertOutcome] = []
    for idx, alert in enumerate(admitted):
        results: list[ChannelResult] = []
        for channel_name, channel_results in per_channel.items():
            if idx < len(channel_results):
                results.append(channel_results[idx])
            else:
                results.append(
                    ChannelResult(
                        alert_id=alert.alert_id,
                        channel=channel_name,
                        status="failed",
                        sent_at=datetime.now(tz=UTC),
                        error="channel returned fewer results than alerts",
                    )
                )
        outcomes.append(AlertOutcome(alert=alert, results=tuple(results)))
    return outcomes


def _channel_status_rollup(
    per_channel: dict[str, list[ChannelResult]],
) -> dict[str, dict[str, int]]:
    rollup: dict[str, dict[str, int]] = {}
    for channel, results in per_channel.items():
        per_status: dict[str, int] = {}
        for result in results:
            per_status[result.status] = per_status.get(result.status, 0) + 1
        rollup[channel] = per_status
    return rollup


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)
