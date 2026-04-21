"""FastAPI application factory.

``create_app`` wires the routers, CORS, structured-logging middleware, and a
catch-all exception handler so tracebacks never leak to clients. Anything
that needs process lifetime (lake, settings) is stashed on ``app.state``; no
module-level globals.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from superbrain.api.config import Settings
from superbrain.api.logging_config import configure_logging
from superbrain.api.middleware import RequestContextMiddleware
from superbrain.api.routers import backtest as backtest_router
from superbrain.api.routers import bets as bets_router
from superbrain.api.routers import health as health_router
from superbrain.api.routers import matches as matches_router
from superbrain.api.routers import odds as odds_router
from superbrain.api.routers import scrapers as scrapers_router
from superbrain.api.routers import trends as trends_router
from superbrain.data.connection import Lake


def create_app(settings: Settings | None = None, *, lake: Lake | None = None) -> FastAPI:
    """Build the FastAPI app bound to ``settings`` (loaded from env if omitted).

    :param settings: configuration; defaults to a freshly-constructed
        :class:`Settings` (reads env / ``.env``)
    :param lake: pre-built lake; defaults to one rooted at ``settings.lake_path``
    :return: configured FastAPI instance
    """
    if settings is None:
        settings = Settings()
    configure_logging(settings.log_level)

    if lake is None:
        lake = Lake(settings.lake_path)

    app = FastAPI(
        title="Superbrain API",
        version="0.1.0",
        description=(
            "Read-side HTTP surface for the Superbrain value-bet platform. "
            "Authenticated with shared bearer tokens; engine endpoints are stubbed "
            "until phase 4a lands."
        ),
    )
    app.state.settings = settings
    app.state.lake = lake

    app.add_middleware(
        RequestContextMiddleware,
        header_name=settings.request_id_header,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", settings.request_id_header],
    )

    app.include_router(health_router.router)
    app.include_router(matches_router.router)
    app.include_router(odds_router.router)
    app.include_router(scrapers_router.router)
    app.include_router(bets_router.router)
    app.include_router(backtest_router.router)
    app.include_router(trends_router.router)

    _install_exception_handler(app)
    return app


def _install_exception_handler(app: FastAPI) -> None:
    logger = structlog.get_logger("superbrain.api.errors")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(status_code=500, content={"detail": "internal"})

    _ = _unhandled


__all__ = ["create_app"]


def _dump_settings(settings: Settings) -> dict[str, Any]:
    """Dev helper for ad-hoc ``repr`` of the active settings (not logged)."""
    return settings.model_dump()
