"""Structured JSON logging configuration."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.context import get_correlation_id, get_request_id, get_sender_id


class JSONFormatter(logging.Formatter):
    """Custom formatter to output logs as single-line JSON records."""

    def format(self, record: logging.LogRecord) -> str:
        # Core log fields
        log_record: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Inject context information if available
        request_id = get_request_id()
        correlation_id = get_correlation_id()
        sender = get_sender_id()

        if request_id:
            log_record["request_id"] = request_id
        if correlation_id:
            log_record["correlation_id"] = correlation_id
        if sender:
            log_record["sender"] = sender

        # Inject custom arguments passed in extra dict (e.g. logger.info("msg", extra={"event": "x"}))
        for key in ["event", "message_type", "status_code", "duration_ms", "whatsapp_message_id"]:
            if hasattr(record, key):
                log_record[key] = getattr(record, key)

        # Handle exceptions
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record)


def setup_logging(log_level: str = "INFO") -> None:
    """Configures the root logger to output structured JSON logs."""
    # Resolve numeric level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear pre-existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Setup standard output handler with JSON Formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

    # Route uvicorn logs to root logger for consistent formatting
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        sub_logger = logging.getLogger(logger_name)
        sub_logger.handlers = []
        sub_logger.propagate = True
