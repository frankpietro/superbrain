"""Global exception handler + structured error logs."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from superbrain.data.connection import Lake


def test_unhandled_error_returns_generic_500_and_logs_structured(
    client: TestClient,
    auth_header: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic failure for test")

    monkeypatch.setattr(Lake, "read_odds", boom)

    with caplog.at_level(logging.ERROR, logger="superbrain.api.errors"):
        resp = client.get("/odds", headers=auth_header)

    assert resp.status_code == 500
    assert resp.json() == {"detail": "internal"}
    assert "synthetic failure for test" not in resp.text

    events = _parse_records(caplog.records)
    assert any(e.get("event") == "unhandled_exception" for e in events), (
        f"no unhandled_exception event in caplog: {[r.message for r in caplog.records]!r}"
    )
    err_event = next(e for e in events if e.get("event") == "unhandled_exception")
    assert err_event["path"] == "/odds"
    assert err_event["method"] == "GET"
    assert err_event["error_type"] == "RuntimeError"


def _parse_records(records: list[logging.LogRecord]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for rec in records:
        msg = rec.getMessage()
        if msg.startswith("{"):
            try:
                out.append(json.loads(msg))
            except json.JSONDecodeError:
                continue
    return out
