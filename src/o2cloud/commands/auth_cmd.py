"""``login`` / ``logout`` / ``whoami`` — authentication commands.

``login`` supports the robust manual paths (``--import-token`` / ``--import-cookie``
accept a ``validationKey`` captured from a browser) and a best-effort
browser-assisted OIDC path (which, because it is SMS-gated, surfaces the authorize
URL and directs the user to the import path — see :mod:`o2cloud.auth.oidc`).
"""

from __future__ import annotations

import typer

from ..auth import oidc
from ..errors import O2CloudError
from ..secrets import SecretStore
from ..service import O2CloudService
from ..session import clear_session
from ..state import emit_fail, emit_ok
from ._options import JSON_OPT, PROFILE_OPT, QUIET_OPT, VERBOSE_OPT, resolve_state
from ._run import run


def login(
    ctx: typer.Context,
    import_token: str | None = typer.Option(
        None,
        "--import-token",
        help="Import a bare validationKey (32 hex). NOTE: usually NOT enough on its "
        "own — O2 also needs the JSESSIONID cookie; prefer --import-cookie.",
    ),
    import_cookie: str | None = typer.Option(
        None,
        "--import-cookie",
        help="Import the full browser Cookie header (JSESSIONID + validationKey + …) "
        "from a logged-in /sapi request — the manual fallback when Playwright is absent.",
    ),
    timeout: int = typer.Option(
        300, "--timeout", help="Seconds to wait for you to finish the browser login."
    ),
    headless: bool = typer.Option(
        False, "--headless/--no-headless", help="Run the login browser headless (cannot pass SMS)."
    ),
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Log in: open a browser and capture the session (default), or import a cookie/token."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    secrets = SecretStore(state.profile)
    try:
        if import_token is not None:
            meta = oidc.import_token(state.config, secrets, import_token, profile=state.profile)
            mode = "import-token"
        elif import_cookie is not None:
            meta = oidc.import_cookie(state.config, secrets, import_cookie, profile=state.profile)
            mode = "import-cookie"
        else:
            meta = oidc.login(
                state.config,
                secrets,
                profile=state.profile,
                timeout_s=float(timeout),
                headless=headless,
            )
            mode = "browser"
    except O2CloudError as exc:
        emit_fail(state, "login", exc)
        return
    emit_ok(
        state,
        "login",
        {"profile": meta.profile, "base_url": meta.base_url, "mode": mode},
        human=f"logged in (profile: {meta.profile}, via {mode})",
    )


def logout(
    ctx: typer.Context,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Clear the stored session for the active profile."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)
    SecretStore(state.profile).clear()
    removed = clear_session(state.profile)
    emit_ok(
        state,
        "logout",
        {"profile": state.profile, "cleared": True, "session_removed": removed},
        human=f"logged out (profile: {state.profile})",
    )


def whoami(
    ctx: typer.Context,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
) -> None:
    """Show the identity of the current session (validates the stored token)."""
    state = resolve_state(ctx, json=json, verbose=verbose, quiet=quiet, profile=profile)

    def _op(svc: O2CloudService) -> dict[str, object]:
        return svc.whoami().model_dump(mode="json", by_alias=True)

    run(state, "whoami", _op)


def register(app: typer.Typer) -> None:
    app.command("login")(login)
    app.command("logout")(logout)
    app.command("whoami")(whoami)


__all__ = ["register", "login", "logout", "whoami"]
