"""Helpers that build the service, run an operation, and emit the result.

Centralises the build→run→emit→close lifecycle so each command stays a thin
signature. All :class:`~o2cloud.errors.O2CloudError`s (including the transport's
auth error when no token is stored) are turned into the proper JSON error
envelope + exit code.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..errors import O2CloudError
from ..output import BatchItem
from ..secrets import SecretStore
from ..service import O2CloudService
from ..state import AppState, emit_fail, emit_items, emit_ok


def build_service(state: AppState) -> O2CloudService:
    """Construct a service for the active profile (no network at construction)."""
    return O2CloudService(state.config, SecretStore(state.profile))


def run(
    state: AppState,
    command: str,
    fn: Callable[[O2CloudService], Any],
    *,
    human: str | None = None,
) -> None:
    """Run ``fn(service)`` and emit a single success/error envelope."""
    service = build_service(state)
    try:
        data = fn(service)
    except O2CloudError as exc:
        emit_fail(state, command, exc)  # raises typer.Exit
        return
    finally:
        service.close()
    emit_ok(state, command, data, human=human)


def run_batch(
    state: AppState,
    command: str,
    fn: Callable[[O2CloudService], list[BatchItem]],
) -> None:
    """Run ``fn(service)`` returning batch items and emit the batch envelope."""
    service = build_service(state)
    try:
        items = fn(service)
    except O2CloudError as exc:
        emit_fail(state, command, exc)  # raises typer.Exit
        return
    finally:
        service.close()
    emit_items(state, command, items)


__all__ = ["build_service", "run", "run_batch"]
