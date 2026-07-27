"""Shared pytest fixtures: isolated config/state dirs and an in-memory keyring."""

from __future__ import annotations

from collections.abc import Iterator

import keyring
import pytest
from keyring.errors import PasswordDeleteError

# Every O2CLOUD_* env var that could leak host configuration into a test.
_LEAKY_ENV = (
    "O2CLOUD_BASE_URL",
    "O2CLOUD_USER_AGENT",
    "O2CLOUD_DEVICE_ID",
    "O2CLOUD_REQUEST_RATE_PER_SEC",
    "O2CLOUD_DEFAULT_REMOTE_ROOT",
    "O2CLOUD_DEFAULT_DOWNLOAD_DIR",
    "O2CLOUD_USERNAME",
    "O2CLOUD_PASSWORD",
    "O2CLOUD_TOKEN",
    "O2CLOUD_COOKIE",
)


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch) -> Iterator[None]:
    """Point config/state at a tmp dir and scrub leaky env for every test."""
    monkeypatch.setenv("O2CLOUD_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("O2CLOUD_STATE_DIR", str(tmp_path / "state"))
    for name in _LEAKY_ENV:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture(autouse=True)
def mock_keyring(monkeypatch) -> Iterator[dict[tuple[str, str], str]]:
    """Replace keyring's storage with an in-memory dict (no OS keychain touched)."""
    store: dict[tuple[str, str], str] = {}

    def _get(service: str, key: str) -> str | None:
        return store.get((service, key))

    def _set(service: str, key: str, value: str) -> None:
        store[(service, key)] = value

    def _delete(service: str, key: str) -> None:
        if (service, key) not in store:
            raise PasswordDeleteError("not found")
        del store[(service, key)]

    monkeypatch.setattr(keyring, "get_password", _get)
    monkeypatch.setattr(keyring, "set_password", _set)
    monkeypatch.setattr(keyring, "delete_password", _delete)
    yield store
