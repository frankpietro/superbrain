"""Entrypoint for ``uvicorn superbrain.api.main:app``."""

from __future__ import annotations

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from superbrain.api.app import create_app

app = create_app()

__all__ = ["app"]
