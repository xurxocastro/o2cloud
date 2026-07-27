"""``config get`` / ``config set`` — the one fully-implemented command group.

Reads/writes non-secret configuration via :mod:`o2cloud.config`. Secrets are never
handled here.
"""

from __future__ import annotations

import typer

from .. import config as config_mod
from ..errors import O2CloudError
from ..state import emit_fail, emit_ok
from ._options import JSON_OPT, PROFILE_OPT, QUIET_OPT, VERBOSE_OPT, resolve_state

config_app = typer.Typer(no_args_is_help=True, help="Manage local non-secret configuration.")


@config_app.command("get")
def config_get(
    ctx: typer.Context,
    key: str | None = typer.Argument(None, help="Config key to read; omit to list all."),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Print a single config value, or every value when no key is given."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    try:
        if key is None:
            data = config_mod.get_all(state.profile)
            human = "\n".join(f"{k} = {v!r}" for k, v in sorted(data.items()))
            emit_ok(state, "config get", data, human=human)
        else:
            value = config_mod.get_value(state.profile, key)
            emit_ok(state, "config get", {key: value}, human=f"{key} = {value!r}")
    except O2CloudError as exc:
        emit_fail(state, "config get", exc)


@config_app.command("set")
def config_set(
    ctx: typer.Context,
    key: str = typer.Argument(..., help="Config key to write."),
    value: str = typer.Argument(..., help="New value."),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Persist ``key = value`` in the active profile's config file."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    try:
        coerced = config_mod.set_value(state.profile, key, value)
        emit_ok(
            state,
            "config set",
            {"key": key, "value": coerced, "profile": state.profile},
            human=f"{key} = {coerced!r}  (profile: {state.profile})",
        )
    except O2CloudError as exc:
        emit_fail(state, "config set", exc)


def register(app: typer.Typer) -> None:
    app.add_typer(config_app, name="config")


__all__ = ["config_app", "register"]
