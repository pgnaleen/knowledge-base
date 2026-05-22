"""Structured logging configuration."""

import logging
import os
import re as _re

import structlog

from config.settings import settings

_configured = False


class _TargetClosedFilter(logging.Filter):
    """Drop the benign scrapy-playwright race-condition error from asyncio logs.

    When a Playwright page closes just as scrapy-playwright tries to read
    response headers, asyncio logs a TargetClosedError callback exception.
    The page was already fully processed — this is harmless noise.

    The error string 'TargetClosedError' appears only in exc_info, not in
    getMessage(), so both are checked.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if "TargetClosedError" in record.getMessage():
            return False
        if record.exc_info and record.exc_info[0] is not None:
            if "TargetClosedError" in record.exc_info[0].__name__:
                return False
        return True


_DOWNLOAD_URL_RE = _re.compile(r"<\w+\s+([^>]+)>")


class _ScrapyDownloadErrorFilter(logging.Filter):
    """Convert Scrapy download-error tracebacks into clean structlog warnings.

    Scrapy logs a full 40-line traceback for every Playwright timeout or
    connection error via scrapy.core.scraper. This filter intercepts those
    records, emits a single-line structlog warning, and suppresses the
    original traceback so the terminal stays readable.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if not msg.startswith("Error downloading"):
            return True

        exc_type = record.exc_info[0] if record.exc_info else None
        exc_name = exc_type.__name__ if exc_type else "DownloadError"

        url_match = _DOWNLOAD_URL_RE.search(msg)
        url = url_match.group(1) if url_match else "unknown"

        structlog.get_logger("scrapy.download").warning(
            "page.download_failed",
            url=url,
            error=exc_name,
        )
        return False


def setup_logging() -> None:
    """Configure structlog once for the application."""
    global _configured
    if _configured:
        return

    # Suppress benign scrapy-playwright race condition from asyncio error handler.
    # The actual logger is asyncio.base_events (shown as [asyncio] by Scrapy's formatter);
    # parent-logger filters don't propagate to child loggers, so we add to both.
    # exc_info must also be checked — "TargetClosedError" is in the exception type,
    # not in getMessage() which only returns the callback description string.
    _tcf = _TargetClosedFilter()
    logging.getLogger("asyncio").addFilter(_tcf)
    logging.getLogger("asyncio.base_events").addFilter(_tcf)

    # Convert scrapy.core.scraper download-error tracebacks into clean one-liners.
    logging.getLogger("scrapy.core.scraper").addFilter(_ScrapyDownloadErrorFilter())

    # Suppress noisy third-party stdlib loggers
    for lib in [
        "pdfminer", "pdfminer.high_level", "pdfminer.layout",
        "httpx", "httpcore", "urllib3", "urllib3.connectionpool",
        "scrapy", "twisted", "playwright",
        "scrapy-playwright", "py.warnings",
    ]:
        logging.getLogger(lib).setLevel(logging.ERROR)

    _log_format = os.getenv("LOG_FORMAT", "console").lower()
    _renderer = (
        structlog.processors.JSONRenderer()
        if _log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog, settings.log_level.upper(), 20)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str):
    """Get a named logger instance."""
    setup_logging()
    return structlog.get_logger(name)


def bind_source_context(source: str) -> None:
    """Bind source to structlog context so all nested logs carry it."""
    structlog.contextvars.bind_contextvars(source=source)


def clear_source_context() -> None:
    """Clear source context from structlog."""
    structlog.contextvars.clear_contextvars()
