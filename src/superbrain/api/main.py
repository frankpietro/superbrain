"""Entrypoint for ``uvicorn superbrain.api.main:app``."""

from __future__ import annotations

from superbrain.api.app import create_app

app = create_app()

__all__ = ["app"]
