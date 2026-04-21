"""Alert delivery channels.

Every channel implements :class:`~superbrain.alerts.channels.base.Channel`
— a tiny protocol with one asynchronous batch-send method. The
dispatcher drives them in parallel.
"""

from superbrain.alerts.channels.base import Channel
from superbrain.alerts.channels.email import EmailChannel
from superbrain.alerts.channels.telegram import TelegramChannel

__all__ = ["Channel", "EmailChannel", "TelegramChannel"]
