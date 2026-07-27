"""Error taxonomy: code slug + exit code mapping is frozen and must not drift."""

from __future__ import annotations

import pytest

from o2cloud import errors


@pytest.mark.parametrize(
    ("cls", "expected_code", "expected_exit"),
    [
        (errors.UsageError, "usage", 1),
        (errors.AuthError, "auth", 2),
        (errors.NotFoundError, "not_found", 3),
        (errors.ConflictError, "conflict", 4),
        (errors.NetworkError, "network", 5),
        (errors.RateLimitedError, "rate_limited", 6),
        (errors.QuotaError, "quota", 7),
        (errors.PartialBatchError, "partial_failure", 8),
    ],
)
def test_error_code_and_exit_mapping(cls, expected_code, expected_exit) -> None:
    err = cls("boom")
    assert err.code == expected_code
    assert err.exit_code == expected_exit
    assert err.message == "boom"


def test_exit_code_constants_are_stable() -> None:
    assert (
        errors.EXIT_OK,
        errors.EXIT_USAGE,
        errors.EXIT_AUTH,
        errors.EXIT_NOT_FOUND,
        errors.EXIT_CONFLICT,
        errors.EXIT_NETWORK,
        errors.EXIT_RATE_LIMITED,
        errors.EXIT_QUOTA,
        errors.EXIT_PARTIAL_BATCH,
    ) == (0, 1, 2, 3, 4, 5, 6, 7, 8)


def test_to_error_dict_includes_detail_when_present() -> None:
    err = errors.NotFoundError("missing", detail={"path": "/x"})
    assert err.to_error_dict() == {
        "code": "not_found",
        "message": "missing",
        "detail": {"path": "/x"},
    }


def test_to_error_dict_omits_empty_detail() -> None:
    err = errors.AuthError("nope")
    assert err.to_error_dict() == {"code": "auth", "message": "nope"}


def test_not_implemented_message_and_detail() -> None:
    err = errors.NotImplementedYetError("ls", detail={"remote": "/"})
    assert err.code == "not_implemented"
    assert err.exit_code == 1
    assert "pending Phase 1" in err.message
    assert "docs/api-reference.md" in err.message
    assert err.detail == {"phase": "phase-1-capture", "command": "ls", "remote": "/"}


def test_not_implemented_without_command() -> None:
    err = errors.NotImplementedYetError()
    assert err.detail == {"phase": "phase-1-capture"}


def test_subclasses_are_o2cloud_errors() -> None:
    assert issubclass(errors.NotImplementedYetError, errors.O2CloudError)
    assert issubclass(errors.QuotaError, errors.O2CloudError)


def test_error_detail_redacts_token_bearing_url() -> None:
    """H1 regression: a token in error detail must not survive into the envelope."""
    import json

    token = "deadbeefdeadbeefdeadbeefdeadbeef"
    err = errors.NetworkError(
        "boom", detail={"url": f"https://cloud.o2online.es/download/x?validationkey={token}"}
    )
    rendered = json.dumps(err.to_error_dict())
    assert token not in rendered  # the secret value is gone
    assert "validationkey" in rendered.lower()  # the (redacted) key remains for context
