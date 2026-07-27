"""``share create/list/revoke`` — share-link management (best-effort).

The list path uses the confirmed ``media/set?action=list-media-sets`` shape;
create/revoke are best-effort with ``TODO(live-capture)`` markers in
:mod:`o2cloud.api.share`.
"""

from __future__ import annotations

import typer

from ..service import O2CloudService
from ._options import JSON_OPT, PROFILE_OPT, QUIET_OPT, VERBOSE_OPT, resolve_state
from ._run import run

share_app = typer.Typer(no_args_is_help=True, help="Manage share links (best-effort).")


@share_app.command("create")
def share_create(
    ctx: typer.Context,
    remote: str = typer.Argument(..., help="Remote item to share."),
    expires: str | None = typer.Option(None, "--expires", help="Expiry (ISO-8601), if supported."),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Create a share link for a remote item."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)

    def _op(svc: O2CloudService) -> dict[str, object]:
        item = svc.resolver.resolve_item(remote)
        link = svc.share.create(item.id, expires_at=expires)
        return link.model_dump(mode="json")

    run(state, "share", _op)


@share_app.command("list")
def share_list(
    ctx: typer.Context,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """List active share links."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    run(
        state,
        "share",
        lambda svc: [s.model_dump(mode="json") for s in svc.share.list()],
    )


@share_app.command("revoke")
def share_revoke(
    ctx: typer.Context,
    share_id: str = typer.Argument(..., help="Share-link id to revoke."),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Revoke a share link."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)

    def _op(svc: O2CloudService) -> dict[str, object]:
        svc.share.revoke(share_id)
        return {"revoked": share_id}

    run(state, "share", _op, human=f"revoked {share_id}")


def register(app: typer.Typer) -> None:
    app.add_typer(share_app, name="share")


__all__ = ["share_app", "register"]
