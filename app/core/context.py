"""Thread-safe request-scoped context variables storage."""

from contextvars import ContextVar
from typing import Optional

# Define ContextVars for tracking identifiers across asyncio tasks
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
sender_id_ctx: ContextVar[Optional[str]] = ContextVar("sender_id", default=None)
timestamp_ctx: ContextVar[Optional[float]] = ContextVar("timestamp", default=None)


def get_request_id() -> Optional[str]:
    """Retrieve the current request ID."""
    return request_id_ctx.get()


def set_request_id(value: Optional[str]) -> None:
    """Set the current request ID."""
    request_id_ctx.set(value)


def get_correlation_id() -> Optional[str]:
    """Retrieve the current correlation ID."""
    return correlation_id_ctx.get()


def set_correlation_id(value: Optional[str]) -> None:
    """Set the current correlation ID."""
    correlation_id_ctx.set(value)


def get_sender_id() -> Optional[str]:
    """Retrieve the current sender ID (phone number or wa_id)."""
    return sender_id_ctx.get()


def set_sender_id(value: Optional[str]) -> None:
    """Set the current sender ID."""
    sender_id_ctx.set(value)


def get_timestamp() -> Optional[float]:
    """Retrieve the current timestamp for the request start."""
    return timestamp_ctx.get()


def set_timestamp(value: Optional[float]) -> None:
    """Set the current request start timestamp."""
    timestamp_ctx.set(value)
