"""Backtest router — stubbed until phase 4a merges.

TODO: wire engine. ``POST /backtest/run`` returns 501 today; it will stream a
sliding-window backtest over SSE once :mod:`superbrain.engine` and
:mod:`superbrain.backtest` land.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from superbrain.api.deps import require_auth

router = APIRouter(prefix="/backtest", tags=["backtest"], dependencies=[Depends(require_auth)])


@router.post("/run")
async def run_backtest() -> dict[str, Any]:
    """Return 501 Not Implemented until the engine integration lands."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="backtest engine integration pending phase 4a merge",
    )
