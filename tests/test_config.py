"""Config store: TOML persistence, env precedence, profiles, validation."""

from __future__ import annotations

import pytest

from o2cloud import config
from o2cloud.errors import UsageError


def test_set_then_get_roundtrip() -> None:
    config.set_value("default", "base_url", "https://example.test")
    assert config.get_value("default", "base_url") == "https://example.test"


def test_set_coerces_numeric_type() -> None:
    coerced = config.set_value("default", "request_rate_per_sec", "2.5")
    assert coerced == 2.5
    assert config.get_value("default", "request_rate_per_sec") == 2.5


def test_config_file_is_written() -> None:
    config.set_value("default", "base_url", "https://example.test")
    assert config.config_file().exists()
    text = config.config_file().read_text(encoding="utf-8")
    assert "[profiles.default]" in text
    # Secrets must never be persisted as config assignments in the file.
    assert "password =" not in text
    assert "token =" not in text
    assert "cookie =" not in text


def test_profiles_are_isolated() -> None:
    config.set_value("default", "base_url", "https://default.test")
    config.set_value("work", "base_url", "https://work.test")
    assert config.get_value("default", "base_url") == "https://default.test"
    assert config.get_value("work", "base_url") == "https://work.test"


def test_env_overrides_toml(monkeypatch) -> None:
    config.set_value("default", "base_url", "https://file.test")
    monkeypatch.setenv("O2CLOUD_BASE_URL", "https://env.test")
    assert config.get_value("default", "base_url") == "https://env.test"


def test_defaults_apply_when_unset() -> None:
    assert config.get_value("default", "base_url") == "https://cloud.o2online.es"
    assert config.get_value("default", "oidc_client_name") == "O2CLOUD_WEB"
    assert config.get_value("default", "oidc_acr_values") == "2"


def test_get_all_excludes_internal_settable_keys() -> None:
    data = config.get_all("default")
    assert "settable_keys" not in data
    assert "base_url" in data and "oidc_redirect_uri" in data


def test_get_unknown_key_raises_usage_error() -> None:
    with pytest.raises(UsageError):
        config.get_value("default", "does_not_exist")


def test_set_unknown_key_raises_usage_error() -> None:
    with pytest.raises(UsageError):
        config.set_value("default", "does_not_exist", "x")


def test_set_invalid_value_raises_usage_error() -> None:
    with pytest.raises(UsageError):
        config.set_value("default", "request_rate_per_sec", "not-a-number")


def test_state_dir_is_profile_scoped() -> None:
    assert config.state_dir("alpha") != config.state_dir("beta")
    assert config.state_dir("alpha").name == "alpha"


def test_set_preserves_other_keys_in_same_profile() -> None:
    config.set_value("default", "base_url", "https://a.test")
    config.set_value("default", "device_id", "dev-123")
    assert config.get_value("default", "base_url") == "https://a.test"
    assert config.get_value("default", "device_id") == "dev-123"
