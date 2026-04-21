"""Request-id + structured-logging middleware."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id to each request and emit structured access logs.

    If the client sends a request id in :attr:`header_name`, we reuse it;
    otherwise we mint a UUID4. The id is echoed back on the response and bound
    to the structlog context for the duration of the request.
    """

    def __init__(self, app: object, *, header_name: str = "x-request-id") -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.header_name = header_name
        self._logger = structlog.get_logger("superbrain.api.access")

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(self.header_name) or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[self.header_name] = request_id
            return response
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._logger.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status=status_code,
                elapsed_ms=round(elapsed_ms, 2),
                client=request.client.host if request.client else None,
            )
            structlog.contextvars.clear_contextvars()
