"""Token/cookie import + validationKey extraction (no network, no real secrets)."""

from __future__ import annotations

import pytest

from o2cloud.auth import oidc
from o2cloud.config import AppConfig
from o2cloud.errors import AuthError
from o2cloud.secrets import SecretStore
from o2cloud.session import load_session

KEY = "0123456789abcdef0123456789abcdef"  # placeholder validationKey (not real)


def test_extract_bare_key() -> None:
    assert oidc.extract_validation_key(KEY) == KEY


def test_extract_from_cookie_pair() -> None:
    assert oidc.extract_validation_key(f"validationKey={KEY}") == KEY


def test_extract_from_full_cookie_header() -> None:
    header = f"JSESSIONID=abc; validationKey={KEY}; other=1"
    assert oidc.extract_validation_key(header) == KEY


def test_extract_uppercase_is_lowercased() -> None:
    assert oidc.extract_validation_key(KEY.upper()) == KEY


def test_extract_from_query_string() -> None:
    assert oidc.extract_validation_key(f"https://x/sapi/media?validationkey={KEY}&a=1") == KEY


def test_extract_invalid_raises() -> None:
    with pytest.raises(AuthError):
        oidc.extract_validation_key("not-a-key")


def test_import_token_persists_secret_and_metadata() -> None:
    store = SecretStore("default")
    meta = oidc.import_token(AppConfig(), store, KEY, profile="default")
    assert store.token == KEY
    assert store.cookie == f"validationKey={KEY}"
    assert meta.base_url == "https://cloud.o2online.es"
    # Non-secret metadata is on disk; the secret is not.
    loaded = load_session("default")
    assert loaded is not None
    assert loaded.keyring_key == "token"


def test_import_cookie_extracts_and_persists() -> None:
    store = SecretStore("default")
    oidc.import_cookie(AppConfig(), store, f"validationKey={KEY}", profile="default")
    assert store.token == KEY


def test_import_cookie_preserves_full_session_header() -> None:
    """The JSESSIONID (real session cookie) must survive import, not just the key."""
    store = SecretStore("default")
    header = f"OptanonConsent=x; JSESSIONID=ABC123.node1; validationKey={KEY}; _ga=y"
    oidc.import_cookie(AppConfig(), store, header, profile="default")
    assert store.token == KEY  # query-param token extracted
    assert store.cookie is not None
    assert "JSESSIONID=ABC123.node1" in store.cookie  # session cookie preserved
    assert f"validationKey={KEY}" in store.cookie


def test_extract_cookie_header_from_curl_dash_b() -> None:
    """A pasted 'Copy as cURL' -b clause is unwrapped to the cookie header."""
    curl = f"curl 'https://x/sapi/y' -b 'JSESSIONID=Z9.n; validationKey={KEY}' -H 'accept: */*'"
    assert oidc.extract_cookie_header(curl) == f"JSESSIONID=Z9.n; validationKey={KEY}"


def test_login_without_playwright_surfaces_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    from o2cloud.auth import browser

    monkeypatch.setattr(browser, "is_available", lambda: False)
    store = SecretStore("default")
    with pytest.raises(AuthError) as exc:
        oidc.login(AppConfig(), store, profile="default")
    assert "authorize_url" in exc.value.detail  # still surfaced for manual use
    assert "install" in exc.value.detail  # + the Playwright/manual hint
