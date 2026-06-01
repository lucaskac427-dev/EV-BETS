"""structlog configuration — JSON output to stdout."""

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Set up structlog with JSON output."""
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()
