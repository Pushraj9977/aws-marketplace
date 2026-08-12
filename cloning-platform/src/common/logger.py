"""
logger.py — Structured JSON logger compatible with CloudWatch Insights.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON for CloudWatch Insights queries."""

    RESERVED_ATTRS = frozenset(
        {"args", "asctime", "created", "exc_info", "exc_text", "filename",
         "funcName", "levelname", "levelno", "lineno", "message", "module",
         "msecs", "msg", "name", "pathname", "process", "processName",
         "relativeCreated", "stack_info", "taskName", "thread", "threadName"}
    )

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "function": os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "local"),
            "region": os.environ.get("AWS_DEFAULT_REGION", "eu-central-1"),
        }

        # Attach extra fields (environment_id, step, etc.)
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and not key.startswith("_"):
                log_data[key] = value

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


def get_logger(
    name: str,
    *,
    environment_id: str = "",
    step: str = "",
    resource_type: str = "",
) -> logging.Logger:
    """
    Returns a structured JSON logger.

    Args:
        name: Logger name (use __name__).
        environment_id: Current clone operation ID.
        step: Current pipeline step name.
        resource_type: AWS resource type being processed.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
        logger.propagate = False

    # Inject correlation context as LoggerAdapter extra
    adapter = logging.LoggerAdapter(logger, extra={
        "environment_id": environment_id,
        "step": step,
        "resource_type": resource_type,
    })
    return adapter  # type: ignore[return-value]
