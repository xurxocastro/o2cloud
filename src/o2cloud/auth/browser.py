"""Browser-assisted login via Playwright (optional extra ``o2cloud[browser]``).

Opens a real (headed) Chromium at the O2 login page; the **user** completes login
(MobileConnect / SMS / OIDC — the agent never types the password nor reads the OTP), then we read
the resulting cookies from the browser **context**, which exposes the httpOnly ``JSESSIONID`` that
``document.cookie`` / a devtools copy cannot. Returns the ``Cookie`` header to persist.

Rationale for this over an OAuth loopback or the app's refresh-token flow: see
``docs/apk-analysis.md``.

``playwright`` is imported **lazily** (only inside functions) so ``import o2cloud`` and the base CLI
never require it. All logic is injectable so the timeout/cancel/cleanup paths are unit-tested with a
fake browser — no real Chromium in CI.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol, cast
from urllib.parse import urlparse

from ..config import AppConfig
from ..errors import AuthError

INSTALL_HINT = (
    "browser login needs Playwright + Chromium. Install one of:\n"
    "  • uv tool install --with playwright --with-executables-from playwright . "
    "&& playwright install chromium\n"
    "  • (dev checkout) uv sync --extra browser && uv run playwright install chromium\n"
    "Or use the manual path: o2cloud login --import-cookie '<full Cookie header>'"
)


def is_available() -> bool:
    """True if the ``playwright`` package is importable (the optional extra)."""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def _domain_matches(cookie: dict[str, Any], host: str) -> bool:
    """Standard cookie domain-match: does *cookie*'s domain apply to *host*?"""
    dom = str(cookie.get("domain", "")).lstrip(".")
    return bool(dom) and (host == dom or host.endswith("." + dom))


def _cookies_to_header(cookies: Sequence[dict[str, Any]], *, host: str | None = None) -> str | None:
    """Build a ``Cookie`` header once the session is complete, else ``None``.

    O2's SAPI needs both the httpOnly ``JSESSIONID`` and the ``validationKey``; a partial
    mid-login cookie set returns ``None`` so we keep polling rather than capturing early. When
    *host* is given, only cookies whose domain applies to that host are considered — so a cookie
    set for a different host visited during login (e.g. the Mi O2 IdP) is never harvested (M1).
    """
    by_name = {
        c.get("name"): c.get("value")
        for c in cookies
        if c.get("name") and (host is None or _domain_matches(c, host))
    }
    js, vk = by_name.get("JSESSIONID"), by_name.get("validationKey")
    if js and vk:
        return f"JSESSIONID={js}; validationKey={vk}"
    return None


def _poll_for_session(
    read_cookies: Callable[[], Sequence[dict[str, Any]]],
    *,
    timeout_s: float,
    host: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    interval_s: float = 1.0,
) -> str | None:
    """Poll ``read_cookies`` until a full session header is available or timeout.

    Returns the ``Cookie`` header, or ``None`` on timeout. Pure w.r.t. the browser: tests drive it
    with a fake ``read_cookies`` and a fake clock.
    """
    deadline = clock() + timeout_s
    while True:
        header = _cookies_to_header(read_cookies(), host=host)
        if header is not None:
            return header
        if clock() >= deadline:
            return None
        sleep(interval_s)


class _Session(Protocol):
    """The minimal browser surface ``browser_login`` needs (real or fake)."""

    def goto(self, url: str) -> None: ...
    def cookies(self) -> Sequence[dict[str, Any]]: ...
    def close(self) -> None: ...


class _MissingChromium(RuntimeError):
    """Raised by the launcher when the Chromium binary is not installed."""


def browser_login(
    config: AppConfig,
    *,
    timeout_s: float = 300.0,
    headless: bool = False,
    _open_session: Callable[..., _Session] | None = None,
    _sleep: Callable[[float], None] = time.sleep,
    _clock: Callable[[], float] = time.monotonic,
) -> str:
    """Drive a browser login and return the captured ``Cookie`` header.

    The user authenticates in the opened window; we harvest cookies from the context. Every failure
    (missing Chromium, launch error, user-closed window, timeout) becomes an :class:`AuthError`, and
    the browser is **always** closed. ``_open_session``/``_sleep``/``_clock`` are test seams.
    """
    open_session = _open_session or _open_real_session
    host = urlparse(config.base_url).hostname  # harvest only cookies for the SAPI host (M1)
    try:
        session = open_session(headless=headless, base_url=config.base_url)
    except _MissingChromium as exc:
        raise AuthError(
            f"Chromium is not installed. {INSTALL_HINT}", detail={"reason": str(exc)}
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive; real launch failures
        raise AuthError(
            f"could not launch browser for login: {exc}", detail={"hint": INSTALL_HINT}
        ) from exc

    try:
        session.goto(config.base_url.rstrip("/") + "/login")
        header = _poll_for_session(
            session.cookies, timeout_s=timeout_s, host=host, sleep=_sleep, clock=_clock
        )
        if header is None:
            raise AuthError(
                "timed out waiting for you to finish logging in "
                "(no JSESSIONID + validationKey captured)",
                detail={"timeout_s": timeout_s},
            )
        return header
    except AuthError:
        raise
    except Exception as exc:  # user closed the window, navigation crashed, …
        # Interpolate only the exception *type* (L2) — never arbitrary exception content.
        raise AuthError(f"browser login was interrupted ({type(exc).__name__})") from exc
    finally:
        # cleanup must never mask the real outcome
        with contextlib.suppress(Exception):
            session.close()


def _open_real_session(*, headless: bool, base_url: str = "") -> _Session:
    """Launch a real Playwright Chromium and wrap it as a :class:`_Session`."""
    from playwright.sync_api import Error as PWError  # lazy
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=headless)
    except PWError as exc:
        pw.stop()
        if "install" in str(exc).lower() or "executable doesn't exist" in str(exc).lower():
            raise _MissingChromium(str(exc)) from exc
        raise
    # If context/page creation fails, tear the browser + driver down (L1) — no leak.
    try:
        context = browser.new_context()
        page = context.new_page()
    except Exception:
        with contextlib.suppress(Exception):
            browser.close()
        with contextlib.suppress(Exception):
            pw.stop()
        raise
    scope = [base_url] if base_url else None

    class _RealSession:
        def goto(self, url: str) -> None:
            page.goto(url, wait_until="domcontentloaded")

        def cookies(self) -> Sequence[dict[str, Any]]:
            # Scope cookies to the SAPI host at the source too (M1, defense-in-depth).
            raw = context.cookies(scope) if scope else context.cookies()
            return cast("Sequence[dict[str, Any]]", raw)

        def close(self) -> None:
            context.close()
            browser.close()
            pw.stop()

    return _RealSession()


__all__ = ["INSTALL_HINT", "is_available", "browser_login"]
