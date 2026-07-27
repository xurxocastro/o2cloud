"""``account`` / ``quota`` — account & storage commands (stubbed)."""

from __future__ import annotations

import typer

from ..api.models import Plan
from ..service import O2CloudService
from ._options import JSON_OPT, PROFILE_OPT, QUIET_OPT, VERBOSE_OPT, resolve_state
from ._run import run


def account(
    ctx: typer.Context,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Show account identity and plan details."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)

    def _op(svc: O2CloudService) -> dict[str, object]:
        acct = svc.account()
        return {
            "account": acct.model_dump(mode="json", by_alias=True),
            "plans": [p.model_dump(mode="json") for p in _safe_plan(svc)],
        }

    run(state, "account", _op)


def _safe_plan(svc: O2CloudService) -> list[Plan]:
    """Plan lookup is best-effort — a missing plan endpoint must not fail account."""
    from ..errors import O2CloudError

    try:
        return svc.plan()
    except O2CloudError:
        return []


def quota(
    ctx: typer.Context,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Show storage usage and limits."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)

    def _op(svc: O2CloudService) -> dict[str, object]:
        q = svc.storage_quota()
        return q.model_dump(mode="json")

    run(state, "quota", _op)


def register(app: typer.Typer) -> None:
    app.command("account")(account)
    app.command("quota")(quota)


__all__ = ["register", "account", "quota"]
