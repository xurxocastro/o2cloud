"""Secret store: keyring primary, env fallback, per-profile namespacing."""

from __future__ import annotations

from o2cloud.secrets import SecretStore, service_name


def test_service_name_is_profile_namespaced() -> None:
    assert service_name("default") == "o2cloud:default"
    assert service_name("work") == "o2cloud:work"


def test_set_and_get_via_keyring(mock_keyring) -> None:
    store = SecretStore("default")
    store.set("token", "abc123")
    assert store.token == "abc123"
    assert (("o2cloud:default", "token"), "abc123") in [(k, v) for k, v in mock_keyring.items()]


def test_env_overrides_keyring(monkeypatch) -> None:
    store = SecretStore("default")
    store.set("token", "from-keyring")
    monkeypatch.setenv("O2CLOUD_TOKEN", "from-env")
    assert store.token == "from-env"


def test_missing_secret_returns_none() -> None:
    store = SecretStore("default")
    assert store.password is None
    assert store.username is None


def test_env_fallback_when_keyring_empty(monkeypatch) -> None:
    monkeypatch.setenv("O2CLOUD_USERNAME", "dni-user")
    monkeypatch.setenv("O2CLOUD_PASSWORD", "pw")
    store = SecretStore("default")
    assert store.username == "dni-user"
    assert store.password == "pw"


def test_profiles_are_isolated() -> None:
    SecretStore("default").set("token", "tok-default")
    SecretStore("work").set("token", "tok-work")
    assert SecretStore("default").token == "tok-default"
    assert SecretStore("work").token == "tok-work"


def test_delete_returns_true_then_false() -> None:
    store = SecretStore("default")
    store.set("token", "x")
    assert store.delete("token") is True
    assert store.delete("token") is False


def test_store_token_with_cookie() -> None:
    store = SecretStore("default")
    store.store_token("t", cookie="c")
    assert store.token == "t"
    assert store.cookie == "c"


def test_clear_removes_all_keyring_secrets(mock_keyring) -> None:
    store = SecretStore("default")
    store.set("token", "t")
    store.set("password", "p")
    store.clear()
    assert store.token is None
    assert store.password is None
    assert mock_keyring == {}
