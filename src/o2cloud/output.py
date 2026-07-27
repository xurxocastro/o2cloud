"""Agent interface contract — JSON envelopes, batch aggregation, stream rules.

This module is the single source of truth for the machine interface described in
``docs/agent-usage.md``. It is deliberately free of Typer/CLI coupling so the
envelope + exit-code logic is unit testable in isolation.

Stream rule
-----------
With ``--json`` **only** the JSON result goes to **stdout**; every log line,
progress bar, and prompt goes to **stderr**. ``--json`` implies non-interactive.
The :func:`emit_success` / :func:`emit_error` / :func:`emit_batch` helpers honour
this by writing the envelope to the *out* stream and nothing else.

Envelopes
---------
Success (single)::

    {"ok": true, "command": "<name>", "data": <result>}

Error (single)::

    {"ok": false, "command": "<name>",
     "error": {"code": "<slug>", "message": "...", "detail": {...}}}

Batch — ``data`` is **always** the per-item array (so it survives a nonzero
outcome). ``ok`` is ``true`` only when every item is ``ok``/``skipped``. When
``ok`` is ``false`` an aggregate ``error`` (code + ``counts`` breakdown)
accompanies the retained ``data``.

Batch aggregation precedence (deterministic process exit code)
--------------------------------------------------------------
* **single item** → that item's code.
* **batch, all same outcome** → that outcome's code
  (all ``ok`` → 0; all ``skipped`` → 0; all ``conflict`` → 4;
  all ``failed`` with **one** common cause → that cause's code).
* **batch, mixed** → any hard ``failed`` ⇒ 8; else any ``conflict`` ⇒ 4;
  else (only ``ok`` + intentional ``skipped``) ⇒ 0.

``skipped`` (intentional ``--skip``) and ``conflict`` (unresolved collision)
never collapse together.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from collections import Counter
from typing import IO, Any, Literal

from .errors import (
    EXIT_CONFLICT,
    EXIT_OK,
    EXIT_PARTIAL_BATCH,
    EXIT_USAGE,
    O2CloudError,
)

ItemStatus = Literal["ok", "skipped", "conflict", "failed"]

_STATUS_EXIT: dict[str, int] = {
    "ok": EXIT_OK,
    "skipped": EXIT_OK,
    "conflict": EXIT_CONFLICT,
}


@dataclasses.dataclass
class BatchItem:
    """One entry in a batch result.

    ``target`` names the item (a path/id). ``failed`` items additionally carry a
    ``code`` slug and an ``exit_code`` (usually derived from the causing
    :class:`~o2cloud.errors.O2CloudError`) so the aggregate exit code can honour
    the "single common cause" rule.
    """

    target: str
    status: ItemStatus
    message: str | None = None
    code: str | None = None
    exit_code: int | None = None
    detail: dict[str, Any] | None = None

    @classmethod
    def ok(cls, target: str, *, message: str | None = None, **detail: Any) -> BatchItem:
        return cls(target=target, status="ok", message=message, detail=detail or None)

    @classmethod
    def skipped(cls, target: str, *, message: str | None = None, **detail: Any) -> BatchItem:
        return cls(target=target, status="skipped", message=message, detail=detail or None)

    @classmethod
    def conflict(cls, target: str, *, message: str | None = None, **detail: Any) -> BatchItem:
        return cls(target=target, status="conflict", message=message, detail=detail or None)

    @classmethod
    def failed(cls, target: str, error: O2CloudError, **detail: Any) -> BatchItem:
        merged = {**error.detail, **detail} if (error.detail or detail) else None
        return cls(
            target=target,
            status="failed",
            message=error.message,
            code=error.code,
            exit_code=error.exit_code,
            detail=merged,
        )

    def item_exit_code(self) -> int:
        """The exit code this single item would produce on its own."""
        if self.status == "failed":
            return self.exit_code if self.exit_code is not None else EXIT_USAGE
        return _STATUS_EXIT[self.status]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"target": self.target, "status": self.status}
        if self.message is not None:
            payload["message"] = self.message
        if self.code is not None:
            payload["code"] = self.code
        if self.detail:
            payload["detail"] = self.detail
        return payload


# --- Pure envelope builders -------------------------------------------------
def success_envelope(command: str, data: Any) -> dict[str, Any]:
    """Build the single-result success envelope."""
    return {"ok": True, "command": command, "data": data}


def error_envelope(command: str, error: O2CloudError) -> dict[str, Any]:
    """Build the single-error envelope."""
    return {"ok": False, "command": command, "error": error.to_error_dict()}


def aggregate_exit_code(items: list[BatchItem]) -> int:
    """Compute the deterministic process exit code for a batch.

    Implements the batch aggregation precedence documented at module level.
    """
    if not items:
        return EXIT_OK
    if len(items) == 1:
        return items[0].item_exit_code()

    statuses = {it.status for it in items}

    # Homogeneous batches.
    if statuses == {"ok"} or statuses == {"skipped"} or statuses <= {"ok", "skipped"}:
        return EXIT_OK
    if statuses == {"conflict"}:
        return EXIT_CONFLICT
    if statuses == {"failed"}:
        failure_codes = {it.item_exit_code() for it in items}
        if len(failure_codes) == 1:
            return failure_codes.pop()
        return EXIT_PARTIAL_BATCH

    # Mixed batches: precedence failed > conflict > ok/skipped.
    if any(it.status == "failed" for it in items):
        return EXIT_PARTIAL_BATCH
    if any(it.status == "conflict" for it in items):
        return EXIT_CONFLICT
    return EXIT_OK


def _aggregate_error(command: str, items: list[BatchItem], exit_code: int) -> dict[str, Any]:
    counts = dict(Counter(it.status for it in items))
    failed = [it for it in items if it.status == "failed"]
    failure_codes = {it.code for it in failed if it.code}

    if exit_code == EXIT_CONFLICT and not failed:
        code = "conflict"
        message = "one or more destinations already exist (use --force/--skip/--rename)"
    elif exit_code == EXIT_PARTIAL_BATCH:
        code = "partial_failure"
        message = "batch completed with mixed failures"
    elif len(failure_codes) == 1:
        code = next(iter(failure_codes))
        message = "all items failed with a common cause"
    else:
        code = "partial_failure"
        message = "batch completed with failures"

    return {"code": code, "message": message, "counts": counts}


def batch_envelope(command: str, items: list[BatchItem]) -> tuple[dict[str, Any], int]:
    """Build the batch envelope and its deterministic exit code.

    Returns ``(envelope, exit_code)``. ``ok`` is ``True`` only when every item is
    ``ok``/``skipped``; otherwise an aggregate ``error`` (with a ``counts``
    breakdown) accompanies the always-present ``data`` array.
    """
    exit_code = aggregate_exit_code(items)
    data = [it.to_dict() for it in items]
    aggregate_ok = all(it.status in ("ok", "skipped") for it in items)

    envelope: dict[str, Any] = {"ok": aggregate_ok, "command": command, "data": data}
    if not aggregate_ok:
        envelope["error"] = _aggregate_error(command, items, exit_code)
    return envelope, exit_code


# --- Emission helpers -------------------------------------------------------
def _write_json(payload: dict[str, Any], out: IO[str]) -> None:
    json.dump(payload, out, ensure_ascii=False, indent=2, sort_keys=False)
    out.write("\n")
    out.flush()


def emit_success(
    command: str,
    data: Any,
    *,
    json_mode: bool,
    out: IO[str] | None = None,
    human: str | None = None,
) -> int:
    """Emit a single success result. Returns exit code 0."""
    stream = out if out is not None else sys.stdout
    if json_mode:
        _write_json(success_envelope(command, data), stream)
    else:
        stream.write((human if human is not None else _human_repr(data)) + "\n")
        stream.flush()
    return EXIT_OK


def emit_error(
    command: str,
    error: O2CloudError,
    *,
    json_mode: bool,
    out: IO[str] | None = None,
) -> int:
    """Emit a single error. Returns the error's exit code.

    Per the stream rule, the JSON error envelope goes to stdout so an agent can
    always parse a machine-readable result; the human form does too (it *is* the
    command's result), while logs live on stderr.
    """
    stream = out if out is not None else sys.stdout
    if json_mode:
        _write_json(error_envelope(command, error), stream)
    else:
        stream.write(f"error [{error.code}]: {error.message}\n")
        stream.flush()
    return error.exit_code


def emit_batch(
    command: str,
    items: list[BatchItem],
    *,
    json_mode: bool,
    out: IO[str] | None = None,
) -> int:
    """Emit a batch result. Returns the aggregate exit code."""
    stream = out if out is not None else sys.stdout
    envelope, exit_code = batch_envelope(command, items)
    if json_mode:
        _write_json(envelope, stream)
    else:
        for item in items:
            line = f"{item.status:>8}  {item.target}"
            if item.message:
                line += f"  — {item.message}"
            stream.write(line + "\n")
        stream.flush()
    return exit_code


def _human_repr(data: Any) -> str:
    if isinstance(data, str):
        return data
    return json.dumps(data, ensure_ascii=False, indent=2)


__all__ = [
    "BatchItem",
    "ItemStatus",
    "success_envelope",
    "error_envelope",
    "batch_envelope",
    "aggregate_exit_code",
    "emit_success",
    "emit_error",
    "emit_batch",
]
