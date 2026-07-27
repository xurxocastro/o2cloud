"""Path normalization helpers and non-secret session metadata."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from o2cloud import paths
from o2cloud.session import SessionMetadata, clear_session, load_session, save_session


def test_normalize_remote_absolute_and_collapsed() -> None:
    assert paths.normalize_remote("") == "/"
    assert paths.normalize_remote("/") == "/"
    assert paths.normalize_remote("foo/bar") == "/foo/bar"
    assert paths.normalize_remote("/foo/../bar") == "/bar"
    assert paths.normalize_remote("foo\\bar") == "/foo/bar"
    assert paths.normalize_remote("/foo/bar/") == "/foo/bar"


def test_remote_basename() -> None:
    assert paths.remote_basename("/foo/bar.txt") == "bar.txt"
    assert paths.remote_basename("/") == "/"


def test_remote_join() -> None:
    assert paths.remote_join("/foo", "bar", "baz") == "/foo/bar/baz"
    assert paths.remote_join("/", "x") == "/x"


def test_session_roundtrip() -> None:
    meta = SessionMetadata(profile="default", base_url="https://cloud.o2online.es", account_id="a1")
    save_session(meta)
    loaded = load_session("default")
    assert loaded is not None
    assert loaded.account_id == "a1"
    assert loaded.base_url == "https://cloud.o2online.es"


def test_session_missing_returns_none() -> None:
    assert load_session("nonexistent") is None


def test_session_clear() -> None:
    save_session(SessionMetadata(profile="default"))
    assert clear_session("default") is True
    assert clear_session("default") is False


def test_session_expiry_logic() -> None:
    fresh = SessionMetadata(expires_at=datetime.now(UTC) + timedelta(hours=1))
    stale = SessionMetadata(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    unknown = SessionMetadata(expires_at=None)
    assert fresh.is_expired() is False
    assert stale.is_expired() is True
    assert unknown.is_expired() is False


def test_session_file_stores_only_lookup_key_not_secret() -> None:
    path = save_session(SessionMetadata(profile="default", keyring_key="token"))
    text = path.read_text(encoding="utf-8")
    # Only the keyring *lookup key* name is stored, never a secret value.
    assert "keyring_key" in text
    assert "password" not in text.lower()
