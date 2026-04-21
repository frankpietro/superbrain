"""FastAPI dependencies: settings, lake access, bearer-token auth.

Every request-scoped dependency lives here. Keeping them small and
side-effect-free makes routers trivial to test with :class:`TestClient`.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from superbrain.api.config import Settings
from superbrain.data.connection import Lake

_BEARER_PREFIX = "bearer "


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


def require_auth(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Bearer-token gate for protected routes.

    Performs a constant-time comparison against each configured token so a
    timing side-channel does not leak which token is closest to correct.

    :param settings: process settings (injected)
    :param authorization: value of the inbound ``Authorization`` header
    :raises HTTPException: 401 if the header is missing, malformed, or
        does not match any registered token
    """
    if not authorization or not authorization.lower().startswith(_BEARER_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[len(_BEARER_PREFIX) :].strip()
    if not token or not _token_matches(token, settings.api_tokens):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _token_matches(candidate: str, tokens: tuple[str, ...]) -> bool:
    candidate_b = candidate.encode("utf-8")
    ok = False
    for t in tokens:
        if hmac.compare_digest(candidate_b, t.encode("utf-8")):
            ok = True
    return ok
