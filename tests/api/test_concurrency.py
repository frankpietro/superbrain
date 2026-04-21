"""20 concurrent requests must not serialize on the DuckDB/polars reads.

The routers offload lake reads to worker threads via ``anyio.to_thread``. If
a future refactor drops that and runs the lake call on the event loop, this
test catches it: 20 deliberately-slow requests should finish in much less
than 20x per-request latency.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from superbrain.data.connection import Lake


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_serialize(
    app: object, lake: Lake, auth_header: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Lake.read_odds

    def slow_read_odds(self: Lake, **kwargs: object) -> object:
        time.sleep(0.1)
        return original(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Lake, "read_odds", slow_read_odds)

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:

        async def one() -> int:
            r = await c.get("/odds", headers=auth_header)
            return r.status_code

        n = 20
        start = time.perf_counter()
        results = await asyncio.gather(*(one() for _ in range(n)))
        elapsed = time.perf_counter() - start

    assert all(code == 200 for code in results)
    assert elapsed < 1.0, (
        f"20 requests took {elapsed:.2f}s — they are serializing. "
        "Check that lake reads run on a worker thread."
    )
