"""``trash ls/restore/empty`` — trash management."""

from __future__ import annotations

import typer

from ..service import O2CloudService
from ._options import JSON_OPT, PROFILE_OPT, QUIET_OPT, VERBOSE_OPT, resolve_state
from ._run import run

trash_app = typer.Typer(no_args_is_help=True, help="Manage the trash.")


@trash_app.command("ls")
def trash_ls(
    ctx: typer.Context,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """List trashed (soft-deleted) items."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    run(
        state,
        "trash",
        lambda svc: [t.model_dump(mode="json") for t in svc.trash.list()],
    )


@trash_app.command("restore")
def trash_restore(
    ctx: typer.Context,
    item_id: str = typer.Argument(..., help="Trashed item id to restore."),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Restore a trashed item (best-effort; see api/trash.py TODO(live-capture))."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)

    def _op(svc: O2CloudService) -> dict[str, object]:
        svc.trash.restore(item_id)
        return {"restored": item_id}

    run(state, "trash", _op, human=f"restored {item_id}")


@trash_app.command("empty")
def trash_empty(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", help="Confirm permanent deletion of all trash."),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Permanently empty the trash."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    if not yes:
        from ..errors import UsageError
        from ..state import emit_fail

        emit_fail(state, "trash", UsageError("refusing to empty trash without --yes"))
        return

    def _op(svc: O2CloudService) -> dict[str, object]:
        removed = svc.trash.empty()
        return {"emptied": True, "removed": removed}

    run(state, "trash", _op, human="trash emptied")


def register(app: typer.Typer) -> None:
    app.add_typer(trash_app, name="trash")


__all__ = ["trash_app", "register"]
