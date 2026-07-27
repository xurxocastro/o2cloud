"""File & folder commands: ls/tree/stat/upload/download/mkdir/mv/cp/rm/search.

The endpoint-independent CLI logic (mutually-exclusive conflict flags and the
"``--to`` required when more than one source" rule) is validated before any
service call; the operations themselves run through :class:`O2CloudService`.
"""

from __future__ import annotations

from pathlib import Path

import typer

from ..errors import O2CloudError, UsageError
from ..output import BatchItem
from ..service import ConflictPolicy, O2CloudService
from ..state import AppState, emit_fail
from ._options import JSON_OPT, PROFILE_OPT, QUIET_OPT, VERBOSE_OPT, resolve_state
from ._run import run, run_batch

_FORCE = typer.Option(False, "--force", help="Overwrite an existing destination.")
_SKIP = typer.Option(False, "--skip", help="Intentionally skip an existing destination (skipped).")
_RENAME = typer.Option(False, "--rename", help="Auto-suffix to avoid an existing destination.")


def _conflict_policy(
    state: AppState, command: str, *, force: bool, skip: bool, rename: bool
) -> ConflictPolicy:
    try:
        return ConflictPolicy.from_flags(force=force, skip=skip, rename=rename)
    except O2CloudError as exc:  # mutually-exclusive flag violation
        emit_fail(state, command, exc)  # raises typer.Exit
        raise  # pragma: no cover - emit_fail already exits


_DETAIL_OPT = typer.Option(
    True,
    "--detail/--no-detail",
    help="Resolve file names/sizes via a batch detail call (default); "
    "--no-detail is faster but lists files by id only.",
)


def ls(
    ctx: typer.Context,
    remote: str = typer.Argument("/", help="Remote folder to list."),
    detail: bool = _DETAIL_OPT,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """List a remote folder."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    run(
        state,
        "ls",
        lambda svc: [i.model_dump(mode="json") for i in svc.list_dir(remote, detail=detail)],
    )


def tree(
    ctx: typer.Context,
    remote: str = typer.Argument("/", help="Remote folder to list recursively."),
    detail: bool = _DETAIL_OPT,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Recursively list a remote folder."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    run(
        state,
        "tree",
        lambda svc: [i.model_dump(mode="json") for i in svc.tree(remote, detail=detail)],
    )


def stat(
    ctx: typer.Context,
    remote: str = typer.Argument(..., help="Remote file or folder."),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Show metadata for a remote file or folder."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    run(state, "stat", lambda svc: svc.stat(remote).model_dump(mode="json"))


def upload(
    ctx: typer.Context,
    sources: list[Path] = typer.Argument(..., help="Local file(s)/dir(s) to upload."),
    to: str | None = typer.Option(
        None, "--to", help="Remote destination. Optional for a single source; required when >1."
    ),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Recurse into directories."),
    force: bool = _FORCE,
    skip: bool = _SKIP,
    rename: bool = _RENAME,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Upload files/dirs to a remote folder. '--to' is required with 2+ sources."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    policy = _conflict_policy(state, "upload", force=force, skip=skip, rename=rename)
    if len(sources) > 1 and to is None:
        emit_fail(
            state, "upload", UsageError("--to is required when more than one source is given")
        )
    dest = to if to is not None else state.config.default_remote_root

    def _op(svc: O2CloudService) -> list[BatchItem]:
        return svc.upload(sources, dest, policy=policy)

    run_batch(state, "upload", _op)


def download(
    ctx: typer.Context,
    remotes: list[str] = typer.Argument(..., help="Remote file(s)/dir(s) to download."),
    to: str | None = typer.Option(
        None, "--to", help="Local destination. Optional for a single source; required when >1."
    ),
    force: bool = _FORCE,
    skip: bool = _SKIP,
    rename: bool = _RENAME,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Download remote files/dirs to a local path. '--to' is required with 2+ sources."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    policy = _conflict_policy(state, "download", force=force, skip=skip, rename=rename)
    if len(remotes) > 1 and to is None:
        emit_fail(
            state, "download", UsageError("--to is required when more than one source is given")
        )
    local_dest = (
        Path(to)
        if to is not None
        else (
            Path(state.config.default_download_dir)
            if state.config.default_download_dir
            else Path.cwd()
        )
    )

    def _op(svc: O2CloudService) -> list[BatchItem]:
        return svc.download(remotes, local_dest, policy=policy)

    run_batch(state, "download", _op)


def mkdir(
    ctx: typer.Context,
    remote: str = typer.Argument(..., help="Remote folder to create."),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Create a remote folder."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)

    def _op(svc: O2CloudService) -> dict[str, object]:
        svc.mkdir(remote)
        return {"created": remote}

    run(state, "mkdir", _op, human=f"created {remote}")


def mv(
    ctx: typer.Context,
    src: str = typer.Argument(..., help="Source remote path."),
    dst: str = typer.Argument(..., help="Destination remote path."),
    force: bool = _FORCE,
    skip: bool = _SKIP,
    rename: bool = _RENAME,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Move/rename a remote item."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    policy = _conflict_policy(state, "mv", force=force, skip=skip, rename=rename)

    def _op(svc: O2CloudService) -> dict[str, object]:
        svc.move(src, dst, policy=policy)
        return {"moved": src, "to": dst}

    run(state, "mv", _op, human=f"moved {src} → {dst}")


def cp(
    ctx: typer.Context,
    src: str = typer.Argument(..., help="Source remote path."),
    dst: str = typer.Argument(..., help="Destination remote path."),
    force: bool = _FORCE,
    skip: bool = _SKIP,
    rename: bool = _RENAME,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Copy a remote item (server-side)."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    policy = _conflict_policy(state, "cp", force=force, skip=skip, rename=rename)

    def _op(svc: O2CloudService) -> dict[str, object]:
        svc.copy(src, dst, policy=policy)
        return {"copied": src, "to": dst}

    run(state, "cp", _op, human=f"copied {src} → {dst}")


def rm(
    ctx: typer.Context,
    remote: str = typer.Argument(..., help="Remote path to delete."),
    permanent: bool = typer.Option(
        False, "--permanent", help="Delete permanently instead of moving to trash."
    ),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Delete a remote item (to trash by default)."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)

    def _op(svc: O2CloudService) -> dict[str, object]:
        svc.remove(remote, permanent=permanent)
        return {"removed": remote, "permanent": permanent}

    run(state, "rm", _op, human=f"removed {remote}")


def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query."),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Search remote items (client-side filter fallback)."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    run(
        state,
        "search",
        lambda svc: [i.model_dump(mode="json") for i in svc.search(query)],
    )


def register(app: typer.Typer) -> None:
    app.command("ls")(ls)
    app.command("tree")(tree)
    app.command("stat")(stat)
    app.command("upload")(upload)
    app.command("download")(download)
    app.command("mkdir")(mkdir)
    app.command("mv")(mv)
    app.command("cp")(cp)
    app.command("rm")(rm)
    app.command("search")(search)


__all__ = [
    "register",
    "ls",
    "tree",
    "stat",
    "upload",
    "download",
    "mkdir",
    "mv",
    "cp",
    "rm",
    "search",
]
