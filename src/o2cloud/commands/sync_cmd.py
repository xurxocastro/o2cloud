"""``sync`` — directory sync.

Mode flags (``--up``/``--down``/``--two-way``) and conflict-resolution flags
(``--prefer-local``/``--prefer-remote``) are validated here (mutually exclusive)
as endpoint-independent CLI logic; execution runs through the three-way
:class:`~o2cloud.sync.SyncEngine`.
"""

from __future__ import annotations

from pathlib import Path

import typer

from ..errors import UsageError
from ..service import O2CloudService
from ..state import emit_fail
from ..sync import ConflictResolution, SyncDirection, SyncEngine
from ._options import JSON_OPT, PROFILE_OPT, QUIET_OPT, VERBOSE_OPT, resolve_state
from ._run import run

_DIRECTIONS = {
    "up": SyncDirection.UP,
    "down": SyncDirection.DOWN,
    "two-way": SyncDirection.TWO_WAY,
}


def sync(
    ctx: typer.Context,
    local: Path = typer.Argument(..., help="Local directory."),
    remote: str = typer.Argument(..., help="Remote directory."),
    up: bool = typer.Option(False, "--up", help="One-way: local → remote."),
    down: bool = typer.Option(False, "--down", help="One-way: remote → local."),
    two_way: bool = typer.Option(False, "--two-way", help="Bidirectional sync."),
    delete: bool = typer.Option(False, "--delete", help="Propagate deletions (confirmed)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the action plan; do not mutate."),
    prefer_local: bool = typer.Option(False, "--prefer-local", help="Resolve conflicts to local."),
    prefer_remote: bool = typer.Option(
        False, "--prefer-remote", help="Resolve conflicts to remote."
    ),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Sync a local directory with a remote directory."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    modes = [name for name, on in (("up", up), ("down", down), ("two-way", two_way)) if on]
    if len(modes) > 1:
        emit_fail(state, "sync", UsageError(f"--{' and --'.join(modes)} are mutually exclusive"))
    if prefer_local and prefer_remote:
        emit_fail(
            state,
            "sync",
            UsageError("--prefer-local and --prefer-remote are mutually exclusive"),
        )
    direction = _DIRECTIONS[modes[0]] if modes else SyncDirection.TWO_WAY
    if prefer_local:
        resolution = ConflictResolution.PREFER_LOCAL
    elif prefer_remote:
        resolution = ConflictResolution.PREFER_REMOTE
    else:
        resolution = ConflictResolution.NONE

    def _op(svc: O2CloudService) -> dict[str, object]:
        engine = SyncEngine(svc, profile=state.profile)
        plan = engine.run(
            local,
            remote,
            direction=direction,
            delete=delete,
            dry_run=dry_run,
            resolution=resolution,
        )
        result = plan.to_dict()
        result["dry_run"] = dry_run
        result["direction"] = direction.value
        return result

    run(state, "sync", _op)


def register(app: typer.Typer) -> None:
    app.command("sync")(sync)


__all__ = ["register", "sync"]
