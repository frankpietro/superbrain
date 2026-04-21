"""FastAPI dependencies: settings and lake access.

Every request-scoped dependency lives here. Keeping them small and
side-effect-free makes routers trivial to test with :class:`TestClient`.
"""

from __future__ import annotations

from fastapi import Request

from superbrain.api.config import Settings
from superbrain.data.connection import Lake


def get_settings(request: Request) -> Settings:
    """Return the :class:`Settings` instance stashed on the app at startup.

    :param request: current request
    :return: process-wide settings
    """
    settings = getattr(request.app.state, "settings", None)
    if settings is None:  # pragma: no cover - create_app always sets it
        raise RuntimeError("Settings not configured on app.state")
    assert isinstance(settings, Settings)
    return settings


def get_lake(request: Request) -> Lake:
    """Return the long-lived :class:`Lake` bound to the app.

    :param request: current request
    :return: process-wide lake
    """
    lake = getattr(request.app.state, "lake", None)
    if lake is None:  # pragma: no cover - create_app always sets it
        raise RuntimeError("Lake not configured on app.state")
    assert isinstance(lake, Lake)
    return lake
