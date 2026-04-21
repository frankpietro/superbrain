"""High-edge value-bet alerts over Telegram and email.

This package is the phase-8 deliverable: a small, composable alert pipeline
that the Phase-5 scheduler (and a GitHub Actions fallback) can invoke after
every scrape cycle.

Public surface
--------------

* :class:`~superbrain.alerts.config.AlertSettings` — env-driven configuration.
* :class:`~superbrain.alerts.models.AlertRecord` — the canonical unit of
  work, derived from a pipeline :class:`~superbrain.engine.pipeline.ValueBet`.
* :class:`~superbrain.alerts.policy.AlertPolicy` — per-run filtering
  (threshold, min-probability, per-match cap, de-dup).
* :class:`~superbrain.alerts.sink.AlertSink` — parquet persistence of
  sent alerts (``data/alerts/sent_alerts.parquet``).
* :class:`~superbrain.alerts.dispatcher.AlertDispatcher` — orchestrates
  policy → channels → sink.
* :func:`~superbrain.alerts.scheduler.run_alert_sweep` — the scheduler
  hook that pulls value bets from the lake and dispatches them.

Side-effect-free imports throughout; nothing touches the network or disk at
import time.
"""

from superbrain.alerts.config import AlertSettings
from superbrain.alerts.dispatcher import AlertDispatcher, AlertRunReport
from superbrain.alerts.models import AlertOutcome, AlertRecord, ChannelResult
from superbrain.alerts.policy import AlertPolicy
from superbrain.alerts.scheduler import run_alert_sweep
from superbrain.alerts.sink import AlertSink

__all__ = [
    "AlertDispatcher",
    "AlertOutcome",
    "AlertPolicy",
    "AlertRecord",
    "AlertRunReport",
    "AlertSettings",
    "AlertSink",
    "ChannelResult",
    "run_alert_sweep",
]
