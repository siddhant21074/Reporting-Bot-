"""Logging middleware for request-response cycle tracing."""

import logging
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.context import get_timestamp

logger = logging.getLogger("app.request")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs incoming HTTP requests and outgoing responses with execution metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        method = request.method
        path = request.url.path
        client_ip = request.client.host if request.client else "unknown"

        logger.info(
            f"Incoming request {method} {path} from {client_ip}",
            extra={
                "event": "http_request_received",
                "method": method,
                "path": path,
                "client_ip": client_ip,
            }
        )

        start_time = get_timestamp() or time.time()

        try:
            response = await call_next(request)
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                f"Outgoing response {method} {path} - {response.status_code} in {duration_ms}ms",
                extra={
                    "event": "http_response_sent",
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }
            )
            return response
            
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.exception(
                f"Exception during request {method} {path} - {str(exc)} in {duration_ms}ms",
                extra={
                    "event": "http_request_exception",
                    "method": method,
                    "path": path,
                    "error": str(exc),
                    "duration_ms": duration_ms,
                }
            )
            raise exc
