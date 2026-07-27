"""Shared CLI application state + emit helpers (kept separate to avoid import cycles).

``AppState`` is stashed on the Typer ``Context.obj`` by the root callback and read
by every command. The ``emit_*`` helpers honour the stream rule (JSON/result on
stdout, logs on stderr) and raise ``typer.Exit`` with the correct code.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

import typer

from .config import DEFAULT_PROFILE, AppConfig, load_config
from .errors import O2CloudError
from .output import BatchItem, emit_batch, emit_error, emit_success


@dataclass
class AppState:
    """Resolved global options for a single CLI invocation."""

    json: bool = False
    verbose: bool = False
    quiet: bool = False
    profile: str = DEFAULT_PROFILE
    _config: AppConfig | None = field(default=None, repr=False)

    @property
    def config(self) -> AppConfig:
        if self._config is None:
            self._config = load_config(self.profile)
        return self._config


def emit_ok(state: AppState, command: str, data: Any, *, human: str | None = None) -> None:
    """Emit a success envelope to stdout and exit 0."""
    code = emit_success(command, data, json_mode=state.json, out=sys.stdout, human=human)
    raise typer.Exit(code)


def emit_fail(state: AppState, command: str, error: O2CloudError) -> None:
    """Emit an error envelope to stdout and exit with the error's code."""
    code = emit_error(command, error, json_mode=state.json, out=sys.stdout)
    raise typer.Exit(code)


def emit_items(state: AppState, command: str, items: list[BatchItem]) -> None:
    """Emit a batch envelope to stdout and exit with the aggregate code."""
    code = emit_batch(command, items, json_mode=state.json, out=sys.stdout)
    raise typer.Exit(code)


__all__ = ["AppState", "emit_ok", "emit_fail", "emit_items"]
