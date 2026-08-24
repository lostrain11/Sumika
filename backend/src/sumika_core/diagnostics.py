"""Private, content-safe diagnostics for the local Sumika core.

The durable SQLite event stream is the product audit trail.  This module is
for operational debugging only: it records lifecycle, boundary, and failure
metadata without recording chat text, provider secrets, or raw media.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGGER_NAME = "sumika.core"
LOG_FILE_NAME = "core.log"
_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]+\b"),
)


class _CompactFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z")
        message = redact_text(record.getMessage())
        return f"{timestamp} {record.levelname:<7} {record.name} {message}"


def redact_text(value: object) -> str:
    """Return a printable diagnostic string with common secret forms masked."""
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1) if match.lastindex else ''}[REDACTED]", text)
    return text


def safe_error(error: BaseException) -> dict[str, str]:
    """Describe an exception without making its message part of the audit API."""
    return {"type": type(error).__name__, "message": redact_text(error)}


def configure_logging(data_dir: Path | None) -> tuple[logging.Logger, Path | None]:
    """Configure the core logger once and return its effective log path."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    target_path = str((data_dir / "logs" / LOG_FILE_NAME).resolve()) if data_dir is not None else None
    for handler in list(logger.handlers):
        if getattr(handler, "sumika_target", None) == target_path:
            return logger, Path(target_path) if target_path else None
        logger.removeHandler(handler)
        handler.close()

    formatter = _CompactFormatter()
    if data_dir is not None:
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / LOG_FILE_NAME
        handler: logging.Handler = RotatingFileHandler(
            log_path,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    else:
        log_path = None
        handler = logging.NullHandler()
    handler.sumika_target = target_path  # type: ignore[attr-defined]
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger, log_path


def close_logging(logger: logging.Logger, log_path: Path | None) -> None:
    """Flush and detach the handler owned by one core instance."""
    target_path = str(log_path.resolve()) if log_path else None
    for handler in list(logger.handlers):
        if getattr(handler, "sumika_target", None) != target_path:
            continue
        logger.removeHandler(handler)
        handler.flush()
        handler.close()
