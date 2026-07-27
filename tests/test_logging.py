"""Redaction filter: secrets must never survive a log line."""

from __future__ import annotations

import logging

from o2cloud.logging import RedactingFilter, redact, setup_logging


def test_redacts_authorization_header() -> None:
    assert "abcdef" not in redact("Authorization: Bearer abcdef")
    assert "REDACTED" in redact("Authorization: Bearer abcdef")


def test_redacts_token_and_password_pairs() -> None:
    assert "s3cret" not in redact("password=s3cret")
    assert "tok_123" not in redact("token=tok_123")


def test_redacts_cookie_and_validationkey() -> None:
    assert "xyz" not in redact("Cookie: JSESSIONID=xyz")
    assert "vkvalue" not in redact("validationkey=vkvalue")


def test_redacts_bare_bearer_token() -> None:
    assert "deadbeef" not in redact("got Bearer deadbeef from idp")


def test_non_secret_text_is_unchanged() -> None:
    assert redact("listing /photos returned 12 items") == "listing /photos returned 12 items"


def test_filter_scrubs_record_message() -> None:
    record = logging.LogRecord(
        name="o2cloud",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="token=supersecret",
        args=(),
        exc_info=None,
    )
    RedactingFilter().filter(record)
    assert "supersecret" not in record.getMessage()


def test_filter_scrubs_record_args() -> None:
    record = logging.LogRecord(
        name="o2cloud",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="auth %s",
        args=("password=hunter2",),
        exc_info=None,
    )
    RedactingFilter().filter(record)
    assert "hunter2" not in record.getMessage()


def test_setup_logging_quiet_beats_verbose() -> None:
    logger = setup_logging(verbose=True, quiet=True)
    assert logger.level == logging.ERROR


def test_setup_logging_verbose_is_debug() -> None:
    logger = setup_logging(verbose=True, quiet=False)
    assert logger.level == logging.DEBUG


def test_setup_logging_is_idempotent_single_handler() -> None:
    setup_logging()
    logger = setup_logging()
    assert len(logger.handlers) == 1
