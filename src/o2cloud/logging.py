"""Structured logging with a mandatory secret-redacting filter.

All logs go to **stderr** (the stream rule reserves stdout for command results /
JSON envelopes). The :class:`RedactingFilter` scrubs credentials, tokens,
``Authorization`` headers, cookies, and ``validationkey`` from every record —
including message args — so a secret can never leak through a log line.

``--verbose`` raises the level to DEBUG; ``--quiet`` lowers it to ERROR.
"""

from __future__ import annotations

import logging
import re
import sys

LOGGER_NAME = "o2cloud"
_REDACTION = "***REDACTED***"

# Case-insensitive patterns matching "<sensitive-key><sep><value>". The value run
# stops at whitespace, comma, or a quote so surrounding text is preserved.
_SECRET_KEY_RE = re.compile(
    r"(?i)\b(authorization|cookie|set-cookie|token|access_token|refresh_token|"
    r"id_token|password|passwd|pwd|secret|validationkey|api[_-]?key|jsessionid)\b"
    r"(\s*[:=]\s*|\s+)"
    r"(?:bearer\s+)?"
    r"([^\s,;\"']+)"
)

# Bearer tokens that appear without an explicit key.
_BEARER_RE = re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._\-]+)")


def redact(text: str) -> str:
    """Return *text* with any recognised secret values replaced by a placeholder."""

    def _key_sub(match: re.Match[str]) -> str:
        key, sep, _value = match.group(1), match.group(2), match.group(3)
        return f"{key}{sep}{_REDACTION}"

    scrubbed = _SECRET_KEY_RE.sub(_key_sub, text)
    scrubbed = _BEARER_RE.sub(f"Bearer {_REDACTION}", scrubbed)
    return scrubbed


class RedactingFilter(logging.Filter):
    """Logging filter that redacts secrets from the message and its args."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - Filter API
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub(v) for k, v in record.args.items()}
            else:
                record.args = tuple(self._scrub(a) for a in record.args)
        return True

    @staticmethod
    def _scrub(value: object) -> object:
        return redact(value) if isinstance(value, str) else value


def setup_logging(*, verbose: bool = False, quiet: bool = False) -> logging.Logger:
    """Configure and return the package logger (idempotent).

    Precedence: ``quiet`` wins over ``verbose`` if both are set.
    """
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    # Reconfigure a single stderr handler each call so repeated setup is safe.
    for existing in list(logger.handlers):
        logger.removeHandler(existing)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    """Return the package logger (configure via :func:`setup_logging` first)."""
    return logging.getLogger(LOGGER_NAME)


__all__ = ["RedactingFilter", "redact", "setup_logging", "get_logger", "LOGGER_NAME"]
