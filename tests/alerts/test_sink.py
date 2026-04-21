"""Tests for :class:`AlertSink` — parquet round-trip + natural-key dedup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from superbrain.alerts.models import AlertOutcome, AlertRecord, ChannelResult
from superbrain.alerts.sink import SINK_SCHEMA, AlertSink
from tests.alerts.conftest import make_value_bet


def _alert(selection: str = "OVER") -> AlertRecord:
    return AlertRecord.from_value_bet(make_value_bet(selection=selection))


def _outcome(
    alert: AlertRecord,
    *,
    channel: str = "telegram",
    status: str = "sent",
    sent_at: datetime | None = None,
    error: str = "",
) -> AlertOutcome:
    result = ChannelResult(
        alert_id=alert.alert_id,
        channel=channel,
        status=status,
        sent_at=sent_at or datetime.now(tz=UTC),
        error=error,
    )
    return AlertOutcome(alert=alert, results=(result,))


def test_empty_sink_loads_empty_frame(tmp_path: Path) -> None:
    sink = AlertSink(tmp_path / "sent.parquet")
    df = sink.load()
    assert df.is_empty()
    assert df.schema == SINK_SCHEMA


def test_round_trip_preserves_every_column(tmp_path: Path) -> None:
    sink = AlertSink(tmp_path / "sent.parquet")
    alert = _alert()
    sent_at = datetime(2025, 5, 18, 10, 0, tzinfo=UTC)
    sink.record([_outcome(alert, sent_at=sent_at)])

    df = sink.load()
    assert df.height == 1
    row = df.to_dicts()[0]
    assert row["alert_id"] == alert.alert_id
    assert row["bet_code"] == alert.bet_code
    assert row["match_id"] == alert.match_id
    assert row["bookmaker"] == alert.bookmaker
    assert row["selection"] == alert.selection
    assert row["odds"] == alert.odds
    assert row["channel"] == "telegram"
    assert row["status"] == "sent"
    assert row["error"] == ""
    assert row["sent_at"].tzinfo is not None


def test_multiple_channels_produce_one_row_per_channel(tmp_path: Path) -> None:
    sink = AlertSink(tmp_path / "sent.parquet")
    alert = _alert()
    outcomes = [
        AlertOutcome(
            alert=alert,
            results=(
                ChannelResult(
                    alert_id=alert.alert_id,
                    channel="telegram",
                    status="sent",
                    sent_at=datetime(2025, 5, 18, 10, 0, tzinfo=UTC),
                ),
                ChannelResult(
                    alert_id=alert.alert_id,
                    channel="email",
                    status="sent",
                    sent_at=datetime(2025, 5, 18, 10, 1, tzinfo=UTC),
                ),
            ),
        )
    ]
    sink.record(outcomes)
    df = sink.load()
    assert df.height == 2
    assert set(df.get_column("channel").to_list()) == {"telegram", "email"}


def test_same_day_rewrite_dedupes_on_natural_key(tmp_path: Path) -> None:
    sink = AlertSink(tmp_path / "sent.parquet")
    alert = _alert()
    first = _outcome(alert, sent_at=datetime(2025, 5, 18, 8, 0, tzinfo=UTC))
    second = _outcome(
        alert,
        status="partial",
        sent_at=datetime(2025, 5, 18, 9, 0, tzinfo=UTC),
        error="one chat failed",
    )
    sink.record([first])
    sink.record([second])
    df = sink.load()
    assert df.height == 1
    row = df.to_dicts()[0]
    assert row["status"] == "partial"
    assert row["error"] == "one chat failed"


def test_load_alerted_ids_filters_by_window_and_status(tmp_path: Path) -> None:
    sink = AlertSink(tmp_path / "sent.parquet")
    alert_sent = AlertRecord.from_value_bet(make_value_bet(selection="OVER"))
    alert_failed = AlertRecord.from_value_bet(make_value_bet(selection="UNDER"))
    sent_at_recent = datetime(2025, 5, 18, 10, 0, tzinfo=UTC)
    sink.record(
        [
            _outcome(alert_sent, status="sent", sent_at=sent_at_recent),
            _outcome(alert_failed, status="failed", sent_at=sent_at_recent),
        ]
    )

    ids_recent = sink.load_alerted_ids(since=sent_at_recent - timedelta(hours=1))
    assert ids_recent == {alert_sent.alert_id}

    ids_old_window = sink.load_alerted_ids(since=sent_at_recent + timedelta(hours=1))
    assert ids_old_window == set()


def test_load_with_since_filters_rows(tmp_path: Path) -> None:
    sink = AlertSink(tmp_path / "sent.parquet")
    alert_a = AlertRecord.from_value_bet(make_value_bet(selection="OVER"))
    alert_b = AlertRecord.from_value_bet(make_value_bet(selection="UNDER"))
    sink.record(
        [
            _outcome(alert_a, sent_at=datetime(2025, 5, 1, tzinfo=UTC)),
            _outcome(alert_b, sent_at=datetime(2025, 5, 18, tzinfo=UTC)),
        ]
    )
    df = sink.load(since=datetime(2025, 5, 10, tzinfo=UTC))
    assert df.height == 1
    assert df.get_column("alert_id").to_list() == [alert_b.alert_id]


def test_parquet_file_is_valid_after_multiple_rewrites(tmp_path: Path) -> None:
    sink = AlertSink(tmp_path / "sent.parquet")
    base_time = datetime(2025, 5, 18, 10, 0, tzinfo=UTC)
    for i in range(5):
        alert = AlertRecord.from_value_bet(make_value_bet(selection=f"S{i}", odds=1.80 + 0.01 * i))
        sink.record([_outcome(alert, sent_at=base_time + timedelta(minutes=i))])

    direct = pl.read_parquet(sink.path)
    assert direct.height == 5
    assert set(direct.columns) == set(SINK_SCHEMA.names())
