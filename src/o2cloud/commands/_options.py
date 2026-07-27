"""Reusable global CLI options + per-command state resolution.

Global options (``--json``, ``--verbose``, ``--quiet``, ``--profile``) are accepted
**both** before the command (via the root callback) and after it (on each command),
so ``o2cloud --json ls`` and ``o2cloud ls --json`` behave identically. Booleans are
OR-merged with the root callback's values; ``--profile`` overrides the root's when
given explicitly.
"""

from __future__ import annotations

import typer

from ..config import DEFAULT_PROFILE
from ..logging import setup_logging
from ..state import AppState

# Shared OptionInfo defaults — safe to reuse across command signatures.
JSON_OPT = typer.Option(
    False, "--json", help="Emit a machine-readable JSON envelope on stdout (non-interactive)."
)
VERBOSE_OPT = typer.Option(False, "--verbose", "-v", help="Verbose logging on stderr (DEBUG).")
QUIET_OPT = typer.Option(False, "--quiet", "-q", help="Quiet logging on stderr (errors only).")
PROFILE_OPT = typer.Option(
    DEFAULT_PROFILE, "--profile", help="Config/credential profile to use.", show_default=True
)


def resolve_state(
    ctx: typer.Context,
    *,
    json: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    profile: str = DEFAULT_PROFILE,
) -> AppState:
    """Merge root-callback state with command-level flags and configure logging."""
    root = ctx.obj if isinstance(ctx.obj, AppState) else AppState()
    merged = AppState(
        json=root.json or json,
        verbose=root.verbose or verbose,
        quiet=root.quiet or quiet,
        profile=profile if profile != DEFAULT_PROFILE else root.profile,
    )
    setup_logging(verbose=merged.verbose, quiet=merged.quiet)
    ctx.obj = merged
    return merged


__all__ = [
    "JSON_OPT",
    "VERBOSE_OPT",
    "QUIET_OPT",
    "PROFILE_OPT",
    "resolve_state",
]
