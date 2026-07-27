"""Browser-assisted login: pure helpers + browser_login error paths + oidc dispatch.

No real Chromium/Playwright is used — a fake session and a fake clock drive every path.
"""

from __future__ import annotations

import pytest

from o2cloud.auth import browser, oidc
from o2cloud.config import AppConfig
from o2cloud.errors import AuthError
from o2cloud.secrets import SecretStore

_H = "cloud.o2online.es"
FULL = [
    {"name": "OptanonConsent", "value": "x", "domain": _H},
    {"name": "JSESSIONID", "value": "ABC123.node1", "domain": _H},
    {"name": "validationKey", "value": "0123456789abcdef0123456789abcdef", "domain": _H},
]
PARTIAL = [{"name": "validationKey", "value": "0123456789abcdef0123456789abcdef", "domain": _H}]


# --- pure helpers -----------------------------------------------------------
def test_cookies_to_header_requires_both() -> None:
    assert browser._cookies_to_header(FULL) == (
        "JSESSIONID=ABC123.node1; validationKey=0123456789abcdef0123456789abcdef"
    )
    assert browser._cookies_to_header(PARTIAL) is None
    assert browser._cookies_to_header([]) is None


def test_cookies_from_other_host_are_not_harvested() -> None:
    """M1: a JSESSIONID/validationKey set for a DIFFERENT host (e.g. the IdP) is ignored."""
    idp = [
        {"name": "JSESSIONID", "value": "EVIL.n", "domain": "t3.o2online.es"},
        {
            "name": "validationKey",
            "value": "0123456789abcdef0123456789abcdef",
            "domain": "t3.o2online.es",
        },
    ]
    assert browser._cookies_to_header(idp, host="cloud.o2online.es") is None
    # A parent-domain cookie (.o2online.es) DOES apply to the SAPI host.
    parent = [
        {"name": "JSESSIONID", "value": "S.n", "domain": ".o2online.es"},
        {
            "name": "validationKey",
            "value": "0123456789abcdef0123456789abcdef",
            "domain": ".o2online.es",
        },
    ]
    assert browser._cookies_to_header(parent, host="cloud.o2online.es") is not None


def test_poll_returns_header_once_complete() -> None:
    seq = iter([PARTIAL, PARTIAL, FULL])  # session completes on the 3rd poll
    header = browser._poll_for_session(
        lambda: next(seq), timeout_s=100, sleep=lambda _s: None, clock=lambda: 0.0
    )
    assert header is not None and "JSESSIONID=ABC123.node1" in header


def test_poll_times_out() -> None:
    ticks = iter([0.0, 1.0, 2.0, 3.0, 99.0])  # clock crosses the deadline
    header = browser._poll_for_session(
        lambda: PARTIAL, timeout_s=5, sleep=lambda _s: None, clock=lambda: next(ticks)
    )
    assert header is None


# --- browser_login (fake session) ------------------------------------------
class _FakeSession:
    def __init__(self, cookies: list[dict[str, str]], *, goto_raises: bool = False) -> None:
        self._cookies = cookies
        self._goto_raises = goto_raises
        self.closed = False

    def goto(self, url: str) -> None:
        if self._goto_raises:
            raise RuntimeError("user closed the window")

    def cookies(self) -> list[dict[str, str]]:
        return self._cookies

    def close(self) -> None:
        self.closed = True


def test_browser_login_success_and_closes() -> None:
    sess = _FakeSession(FULL)
    header = browser.browser_login(
        AppConfig(), _open_session=lambda **_k: sess, _sleep=lambda _s: None, _clock=lambda: 0.0
    )
    assert header.startswith("JSESSIONID=ABC123.node1")
    assert sess.closed  # always closed


def test_browser_login_timeout_is_autherror_and_closes() -> None:
    sess = _FakeSession(PARTIAL)  # never completes
    ticks = iter([0.0, 1.0, 999.0])
    with pytest.raises(AuthError) as exc:
        browser.browser_login(
            AppConfig(),
            timeout_s=5,
            _open_session=lambda **_k: sess,
            _sleep=lambda _s: None,
            _clock=lambda: next(ticks),
        )
    assert "timed out" in str(exc.value)
    assert sess.closed


def test_browser_login_user_close_is_autherror_and_closes() -> None:
    sess = _FakeSession(FULL, goto_raises=True)
    with pytest.raises(AuthError) as exc:
        browser.browser_login(AppConfig(), _open_session=lambda **_k: sess)
    assert "interrupted" in str(exc.value)
    assert sess.closed


def test_browser_login_missing_chromium_gives_install_hint() -> None:
    def _raise(**_k: object) -> browser._Session:
        raise browser._MissingChromium("Executable doesn't exist")

    with pytest.raises(AuthError) as exc:
        browser.browser_login(AppConfig(), _open_session=_raise)
    assert "install" in str(exc.value).lower()


# --- oidc.login dispatch ----------------------------------------------------
def test_login_dispatches_and_forwards(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def _fake_login(config: AppConfig, *, timeout_s: float, headless: bool) -> str:
        calls["timeout_s"] = timeout_s
        calls["headless"] = headless
        return "JSESSIONID=S.n; validationKey=0123456789abcdef0123456789abcdef"

    monkeypatch.setattr(browser, "is_available", lambda: True)
    monkeypatch.setattr(browser, "browser_login", _fake_login)
    store = SecretStore("default")
    meta = oidc.login(AppConfig(), store, profile="default", timeout_s=42.0, headless=True)
    assert calls == {"timeout_s": 42.0, "headless": True}  # forwarded verbatim
    assert store.token == "0123456789abcdef0123456789abcdef"
    assert store.cookie is not None and "JSESSIONID=S.n" in store.cookie
    assert meta.profile == "default"


def test_login_without_playwright_raises_with_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser, "is_available", lambda: False)
    with pytest.raises(AuthError) as exc:
        oidc.login(AppConfig(), SecretStore("default"), profile="default")
    assert "import-cookie" in str(exc.value)  # manual fallback surfaced
