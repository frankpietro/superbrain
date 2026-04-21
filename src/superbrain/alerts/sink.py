"""Parquet-backed log of fired alerts.

One row per ``(alert, channel)`` attempt. The sink is append-only across
runs; in-memory dedup on the natural key
``(alert_id, channel, kickoff_date)`` collapses same-day re-writes to
one row per ``(alert, channel)`` so re-running the CLI entry-point
doesn't bloat the log.

This file is the durable signal the dispatcher reads back at the top of
every sweep to decide whether an alert has already been sent — the
policy consumes the ``alert_id`` set returned by :meth:`AlertSink.load_alerted_ids`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from superbrain.alerts.models import AlertOutcome, AlertRecord, ChannelResult

logger = logging.getLogger(__name__)

SINK_SCHEMA: pl.Schema = pl.Schema(
    [
        ("alert_id", pl.String),
        ("bet_code", pl.String),
        ("match_id", pl.String),
        ("bookmaker", pl.String),
        ("selection", pl.String),
        ("edge", pl.Float64),
        ("probability", pl.Float64),
        ("odds", pl.Float64),
        ("kickoff", pl.Datetime(time_zone="UTC")),
        ("channel", pl.String),
        ("sent_at", pl.Datetime(time_zone="UTC")),
        ("status", pl.String),
        ("error", pl.String),
    ]
)

_SENT_STATUSES: frozenset[str] = frozenset({"sent", "partial"})


class AlertSink:
    """Persistent log of every alert the dispatcher has tried to send.

    :param path: parquet file path; parent directories are created on first
        write. Reads against a missing file return an empty frame.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self, *, since: datetime | None = None) -> pl.DataFrame:
        """Return every row in the sink, optionally filtered by ``sent_at``.

        :param since: keep only rows with ``sent_at >= since`` (timezone-aware).
        :return: polars frame matching :data:`SINK_SCHEMA`; empty when the
            sink file doesn't exist yet.
        """
        if not self._path.exists():
            return pl.DataFrame(schema=SINK_SCHEMA)
        df = pl.read_parquet(self._path)
        if since is not None:
            since_utc = _ensure_utc(since)
            df = df.filter(pl.col("sent_at") >= since_utc)
        return df

    def load_alerted_ids(self, *, since: datetime) -> set[str]:
        """Return alert ids that succeeded (``sent`` / ``partial``) since ``since``.

        :param since: window lower bound.
        :return: alert-id set; empty when the sink is empty.
        """
        df = self.load(since=since)
        if df.is_empty():
            return set()
        df = df.filter(pl.col("status").is_in(list(_SENT_STATUSES)))
        if df.is_empty():
            return set()
        return set(df.get_column("alert_id").to_list())

    def record(self, outcomes: Iterable[AlertOutcome]) -> int:
        """Append every ``(alert, channel_result)`` pair to the parquet log.

        The write is atomic: we build the merged frame in-memory (existing
        rows + new rows, deduped by natural key with the newer ``sent_at``
        winning), then rewrite the file.

        :param outcomes: the dispatcher's per-alert outcome list.
        :return: number of rows written (after dedup).
        """
        new_rows: list[dict[str, object]] = []
        for outcome in outcomes:
            for result in outcome.results:
                new_rows.append(_row_from_result(outcome.alert, result))

        if not new_rows:
            return 0

        new_frame = pl.DataFrame(new_rows, schema=SINK_SCHEMA)
        existing = self.load()
        if existing.is_empty():
            merged = new_frame
        else:
            merged = pl.concat([existing, new_frame], how="vertical_relaxed")

        merged = merged.with_columns(pl.col("kickoff").dt.date().alias("__kickoff_day__"))
        merged = merged.sort("sent_at").unique(
            subset=["alert_id", "channel", "__kickoff_day__"],
            keep="last",
            maintain_order=True,
        )
        merged = merged.drop("__kickoff_day__")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        merged.write_parquet(self._path)
        logger.info(
            "alerts.sink wrote %d rows (total=%d) to %s",
            len(new_rows),
            merged.height,
            self._path,
        )
        return merged.height


def _row_from_result(alert: AlertRecord, result: ChannelResult) -> dict[str, object]:
    return {
        "alert_id": alert.alert_id,
        "bet_code": alert.bet_code,
        "match_id": alert.match_id,
        "bookmaker": alert.bookmaker,
        "selection": alert.selection,
        "edge": alert.edge,
        "probability": alert.probability,
        "odds": alert.odds,
        "kickoff": _ensure_utc(alert.kickoff),
        "channel": result.channel,
        "sent_at": _ensure_utc(result.sent_at),
        "status": result.status,
        "error": result.error or "",
    }


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
