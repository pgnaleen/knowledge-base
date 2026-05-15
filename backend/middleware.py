"""Middleware for structured logging and request tracking."""

import contextvars
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from logging_config import get_logger

# Context var to store request_id across async boundaries
request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)

log = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all incoming requests and outgoing responses with structured data."""

    async def dispatch(self, request: Request, call_next) -> Response:
        """Log request details and measure response time."""
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        request_id_context.set(request_id)

        # Capture request start time
        start_time = time.time()

        # Get request details
        method = request.method
        path = request.url.path
        client_host = request.client.host if request.client else "unknown"

        # Log incoming request
        log.info(
            "request_started",
            request_id=request_id,
            method=method,
            path=path,
            client_host=client_host,
        )

        # Call the next middleware/endpoint
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            # Log exception and re-raise
            duration_ms = int((time.time() - start_time) * 1000)
            log.error(
                "request_failed",
                request_id=request_id,
                method=method,
                path=path,
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise

        # Calculate response duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Log outgoing response
        log.info(
            "request_completed",
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
        )

        return response


def get_request_id() -> str:
    """Get the current request ID from context."""
    return request_id_context.get()
