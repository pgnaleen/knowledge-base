"""Structured logging configuration using structlog.

In development: pretty console output with colors.
In production: JSON lines for easy parsing by log aggregators (Datadog, ELK, etc).
"""

import logging
import os
import sys

import structlog

# Determine environment
ENV = os.getenv("ENV", "development")
IS_PRODUCTION = ENV == "production"


def setup_logging() -> None:
    """Configure structlog for structured logging."""
    # Allow INFO level through structlog's filter_by_level processor
    logging.basicConfig(level=logging.INFO)
    logging.getLogger().setLevel(logging.INFO)

    if IS_PRODUCTION:
        # JSON output for production (machine-readable)
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Pretty console output for development
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),
        ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = __name__):
    """Get a logger instance."""
    return structlog.get_logger(name)
