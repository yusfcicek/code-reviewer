"""Logging configuration.

Diagnostics used to be ``print()`` calls with hand-written ``[INFO]`` prefixes:
32 of them, with no levels and no structure. A noisy run could not be quietened,
a silent failure could not be made louder, and nothing could be shipped to an
aggregator (finding F-47).

Two settings, both from the environment so an operator can change them without
touching the pipeline definition:

``LOG_LEVEL``
    ``DEBUG``, ``INFO`` (default), ``WARNING``, ``ERROR``. An unrecognised value
    falls back to ``INFO`` rather than raising — a typo in a CI variable should
    not stop the review.

``LOG_FORMAT``
    ``text`` (default) for a CI log a human reads, ``json`` for one line per
    record that an aggregator parses.

Structured values travel in ``extra={"fields": {...}}`` rather than being
interpolated into the message, because a message that bakes its values in
cannot be filtered on them (decision D-2).
"""

import json
import logging
import os
import sys
from typing import Any, TextIO

#: Root of the package's logger hierarchy. Configuring this one leaves other
#: libraries' loggers alone.
ROOT_LOGGER_NAME = "code_reviewer"

DEFAULT_LEVEL = logging.INFO

#: Attributes every LogRecord carries; anything else was added by a caller.
_STANDARD_ATTRIBUTES = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "fields",
    "taskName",
}


def _record_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Structured values attached to a record, from ``extra``."""
    fields = dict(getattr(record, "fields", {}) or {})
    for key, value in record.__dict__.items():
        if key not in _STANDARD_ATTRIBUTES and key not in fields:
            fields[key] = value
    return fields


class StructuredFormatter(logging.Formatter):
    """Human-readable line with ``key=value`` pairs appended.

    Values containing spaces are quoted so the pairs stay greppable.
    """

    def __init__(self):
        super().__init__(fmt="%(asctime)s %(levelname)-7s %(name)s | %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = _record_fields(record)
        if not fields:
            return base

        rendered = []
        for key, value in fields.items():
            text = str(value)
            rendered.append(f'{key}="{text}"' if " " in text else f"{key}={text}")
        return f"{base} {' '.join(rendered)}"


class JsonFormatter(logging.Formatter):
    """One JSON object per record, for a log aggregator."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_record_fields(record))

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def _resolve_level(raw: str | None) -> int:
    if not raw:
        return DEFAULT_LEVEL
    level = logging.getLevelName(raw.strip().upper())
    return level if isinstance(level, int) else DEFAULT_LEVEL


def configure_logging(level: str | None = None, stream: TextIO | None = None) -> logging.Logger:
    """Configures the package logger. Safe to call more than once.

    Args:
        level: ``DEBUG``, ``INFO``, ``WARNING`` or ``ERROR``. Overrides
            ``LOG_LEVEL``, so ``--log-level`` beats the environment the way a
            flag should. An unrecognised value falls back rather than raising:
            a review must not be lost to a typo in a pipeline variable.
        stream: Where records go. Defaults to stderr, which keeps diagnostics
            out of anything reading the process's stdout.

    Returns:
        The configured package logger.
    """
    raw_level = level if level else os.getenv("LOG_LEVEL")
    resolved = _resolve_level(raw_level)
    use_json = (os.getenv("LOG_FORMAT") or "").strip().lower() == "json"

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(resolved)
    # The package's records are handled here; letting them reach the root logger
    # as well would print everything twice under pytest and under any host that
    # configures logging itself.
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(JsonFormatter() if use_json else StructuredFormatter())
    handler.setLevel(resolved)
    logger.addHandler(handler)

    if (
        raw_level
        and _resolve_level(raw_level) == DEFAULT_LEVEL
        and raw_level.strip().upper() not in ("INFO",)
    ):
        logger.warning("Unrecognised LOG_LEVEL; using INFO", extra={"fields": {"requested": raw_level}})

    return logger


def get_logger(name: str) -> logging.Logger:
    """Returns a logger under the package hierarchy.

    Modules call ``get_logger(__name__)``; because every module lives under
    ``code_reviewer``, they all inherit the configuration above.
    """
    return logging.getLogger(name)
