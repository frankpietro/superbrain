"""Channel protocol shared by every alert delivery backend."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from superbrain.alerts.models import AlertRecord, ChannelResult


@runtime_checkable
class Channel(Protocol):
    """Minimal interface every alert channel must satisfy.

    :cvar name: short, stable slug used in :class:`AlertRunReport` and the
        sink parquet file.
    """

    name: str

    async def send(self, alerts: Sequence[AlertRecord]) -> list[ChannelResult]:
        """Deliver ``alerts`` and return one :class:`ChannelResult` per alert.

        Implementations MUST return a result for every input alert in
        the same order so the dispatcher can zip them back. The channel
        is responsible for its own retry / backoff policy; idempotency
        is the caller's job.
        """
        ...
