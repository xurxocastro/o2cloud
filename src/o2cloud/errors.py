"""Typed exception hierarchy mapped to the frozen CLI exit-code table.

Exit-code table (frozen at 1.0 — mirrors the agent interface contract in
``docs/agent-usage.md``):

===  ===========================================
 0   success
 1   generic / usage error
 2   authentication failure
 3   not found
 4   destination conflict (non-clobber)
 5   network / transport error
 6   rate limited (HTTP 429)
 7   insufficient quota
 8   partial batch failure
===  ===========================================

Every raisable error carries a machine-readable ``code`` slug (used in the JSON
error envelope) and an ``exit_code`` (the process exit status). The two are kept
in lock-step here so the CLI never has to translate between them ad hoc.
"""

from __future__ import annotations

from typing import Any

# --- Canonical exit codes ---------------------------------------------------
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_AUTH = 2
EXIT_NOT_FOUND = 3
EXIT_CONFLICT = 4
EXIT_NETWORK = 5
EXIT_RATE_LIMITED = 6
EXIT_QUOTA = 7
EXIT_PARTIAL_BATCH = 8


class O2CloudError(Exception):
    """Base class for every o2cloud domain error.

    Subclasses set :attr:`code` (JSON slug) and :attr:`exit_code` (process exit
    status). ``detail`` carries optional structured context surfaced in the JSON
    error envelope.
    """

    code: str = "error"
    exit_code: int = EXIT_USAGE

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail: dict[str, Any] = detail or {}

    def to_error_dict(self) -> dict[str, Any]:
        """Render this error as the ``error`` object of the JSON envelope.

        Message and detail strings are run through the secret redactor so a token
        that leaked into an error (e.g. a token-bearing URL) never reaches the
        ``--json`` envelope on stdout — the log RedactingFilter only covers stderr.
        """
        from .logging import redact

        payload: dict[str, Any] = {"code": self.code, "message": redact(self.message)}
        if self.detail:
            payload["detail"] = _redact_detail(self.detail)
        return payload


def _redact_detail(value: Any) -> Any:
    """Recursively redact secret-bearing strings in an error ``detail`` value."""
    from .logging import redact

    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_detail(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_detail(v) for v in value]
    return value


class UsageError(O2CloudError):
    """Bad CLI usage / generic failure — exit 1."""

    code = "usage"
    exit_code = EXIT_USAGE


class NotImplementedYetError(O2CloudError):
    """A command whose endpoint has not been implemented yet.

    Maps to the generic exit code (1). Raised where an endpoint has not been
    captured; see ``docs/api-reference.md`` for the observed endpoints.
    """

    code = "not_implemented"
    exit_code = EXIT_USAGE

    _MESSAGE = (
        "not yet implemented — pending Phase 1 authenticated API capture "
        "(see docs/api-reference.md)"
    )

    def __init__(self, command: str | None = None, *, detail: dict[str, Any] | None = None) -> None:
        merged: dict[str, Any] = {"phase": "phase-1-capture"}
        if command:
            merged["command"] = command
        if detail:
            merged.update(detail)
        super().__init__(self._MESSAGE, detail=merged)


class AuthError(O2CloudError):
    """Authentication / authorization failure — exit 2."""

    code = "auth"
    exit_code = EXIT_AUTH


class NotFoundError(O2CloudError):
    """Remote or local target does not exist — exit 3."""

    code = "not_found"
    exit_code = EXIT_NOT_FOUND


class ConflictError(O2CloudError):
    """Non-clobbering destination collision with no override flag — exit 4."""

    code = "conflict"
    exit_code = EXIT_CONFLICT


class NetworkError(O2CloudError):
    """Network / transport failure — exit 5."""

    code = "network"
    exit_code = EXIT_NETWORK


class RateLimitedError(O2CloudError):
    """Server returned HTTP 429 — exit 6."""

    code = "rate_limited"
    exit_code = EXIT_RATE_LIMITED


class QuotaError(O2CloudError):
    """Operation would exceed the account's storage quota — exit 7."""

    code = "quota"
    exit_code = EXIT_QUOTA


class ServerError(O2CloudError):
    """An unmapped SAPI backend error returned in the error envelope — exit 1.

    Carries the raw SAPI ``code``/``cause`` in :attr:`detail` so a caller can see
    the backend's own error slug even when it has no dedicated taxonomy entry.
    A 200 response with an ``error`` body (SAPI's quirk) lands here unless the
    code maps to a more specific type.
    """

    code = "server_error"
    exit_code = EXIT_USAGE


class PartialBatchError(O2CloudError):
    """A batch with mixed hard failures — exit 8.

    Used as the *aggregate* error of a batch envelope when the outcome is a mix
    of failures with more than one root cause. See ``output.py`` for the batch
    aggregation precedence.
    """

    code = "partial_failure"
    exit_code = EXIT_PARTIAL_BATCH


__all__ = [
    "EXIT_OK",
    "EXIT_USAGE",
    "EXIT_AUTH",
    "EXIT_NOT_FOUND",
    "EXIT_CONFLICT",
    "EXIT_NETWORK",
    "EXIT_RATE_LIMITED",
    "EXIT_QUOTA",
    "EXIT_PARTIAL_BATCH",
    "O2CloudError",
    "UsageError",
    "NotImplementedYetError",
    "AuthError",
    "NotFoundError",
    "ConflictError",
    "NetworkError",
    "RateLimitedError",
    "QuotaError",
    "ServerError",
    "PartialBatchError",
]
