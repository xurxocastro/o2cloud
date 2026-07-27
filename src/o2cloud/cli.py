"""o2cloud CLI entry point — Typer app with global options and command wiring.

Global options (``--json``, ``--verbose``, ``--quiet``, ``--profile``, ``--version``)
are available on the root callback and, via ``_options``, on every command so they
work in either position. All commands are wired to the real O2 Cloud SAPI endpoints
documented in ``docs/api-reference.md``.
"""

from __future__ import annotations

import typer

from . import __version__
from .commands import (
    account_cmd,
    auth_cmd,
    config_cmd,
    files_cmd,
    share_cmd,
    sync_cmd,
    trash_cmd,
)
from .commands._options import JSON_OPT, PROFILE_OPT, QUIET_OPT, VERBOSE_OPT
from .logging import setup_logging
from .state import AppState

app = typer.Typer(
    name="o2cloud",
    no_args_is_help=True,
    add_completion=True,  # exposes --install-completion / --show-completion
    rich_markup_mode="rich",
    help=(
        "Scriptable, agent-friendly CLI for [bold]O2 Cloud[/bold] "
        "(Telefónica España — Funambol OneMediaHub / SAPI).\n\n"
        "Manage your personal-cloud storage from the terminal: browse, upload, "
        "download, move, copy, delete and sync files. Every command supports "
        "[cyan]--json[/cyan] for machine-readable output, so agents and scripts can "
        "drive it with stable exit codes.\n\n"
        "[bold]Auth:[/bold] login is federated (Mi O2 OIDC + SMS). Capture your "
        "[cyan]validationKey[/cyan] from a logged-in browser session and run "
        "[cyan]o2cloud login --import-token <key>[/cyan]; the token is stored in the OS keyring."
    ),
    epilog=(
        "[bold]Examples[/bold]\n"
        "  o2cloud login --import-token <validationKey>\n"
        "  o2cloud quota                 # storage usage\n"
        "  o2cloud ls /                  # list root\n"
        "  o2cloud upload photo.jpg --to /\n"
        "  o2cloud download /photo.jpg --to ./\n"
        "  o2cloud sync ./backup /backup --two-way --dry-run\n"
        "  o2cloud quota --json          # machine-readable (for agents/scripts)\n\n"
        "[bold]Exit codes[/bold]  0 ok · 1 usage · 2 auth · 3 not-found · 4 conflict · "
        "5 network · 6 rate-limited · 7 quota · 8 partial-batch\n\n"
        "Discover more: [cyan]o2cloud <command> --help[/cyan] · "
        "shell completion: [cyan]o2cloud --install-completion[/cyan]"
    ),
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"o2cloud {__version__}")
        raise typer.Exit(0)


@app.callback()
def main(
    ctx: typer.Context,
    json: bool = JSON_OPT,
    verbose: bool = VERBOSE_OPT,
    quiet: bool = QUIET_OPT,
    profile: str = PROFILE_OPT,
    version: bool = typer.Option(  # noqa: ARG001 - consumed by the eager callback
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the o2cloud version and exit.",
    ),
) -> None:
    """Root callback: capture global options into the shared :class:`AppState`."""
    ctx.obj = AppState(json=json, verbose=verbose, quiet=quiet, profile=profile)
    setup_logging(verbose=verbose, quiet=quiet)


# Wire command groups.
auth_cmd.register(app)
account_cmd.register(app)
files_cmd.register(app)
sync_cmd.register(app)
share_cmd.register(app)
trash_cmd.register(app)
config_cmd.register(app)


if __name__ == "__main__":  # pragma: no cover
    app()
