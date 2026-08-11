"""Middleware for request context initialization and correlation ID injection."""

import time
import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.constants import HEADER_CORRELATION_ID, HEADER_X_REQUEST_ID
from app.core.context import set_correlation_id, set_request_id, set_timestamp


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns unique request and correlation identifiers to each request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Retrieve incoming correlation ID or generate a new one
        correlation_id = request.headers.get(HEADER_CORRELATION_ID) or \
                         request.headers.get(HEADER_X_REQUEST_ID) or \
                         str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        # Bind to current thread/async context
        set_request_id(request_id)
        set_correlation_id(correlation_id)
        set_timestamp(time.time())

        # Store in request state for convenient route access
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        # Proceed with request pipeline
        response = await call_next(request)

        # Inject correlation identifiers into response headers
        response.headers[HEADER_X_REQUEST_ID] = request_id
        response.headers[HEADER_CORRELATION_ID] = correlation_id

        return response
