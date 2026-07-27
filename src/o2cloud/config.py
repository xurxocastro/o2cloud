"""Non-secret configuration: ``pydantic-settings`` model + per-profile TOML store.

Precedence (highest wins): **process env (``O2CLOUD_*``) → profile TOML file →
built-in defaults**. Secrets never live here — see :mod:`o2cloud.secrets`.

Every account-sensitive artifact is namespaced by ``(profile, base_url)`` under the
profile-scoping rule; this module owns the *config* half of that scoping (the
on-disk TOML is keyed by profile, and ``base_url`` is a first-class field).

Paths honour ``O2CLOUD_CONFIG_DIR`` / ``O2CLOUD_STATE_DIR`` overrides (used by the
test suite and by users who want a non-default location); otherwise they fall back
to ``platformdirs`` locations.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_state_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "o2cloud"
DEFAULT_PROFILE = "default"

# Observed OIDC parameters (docs/api-reference.md). Non-secret; safe defaults.
DEFAULT_OIDC_AUTHORIZE_BASE = "https://t3.o2online.es/acceso/"
DEFAULT_OIDC_CLIENT_NAME = "O2CLOUD_WEB"
DEFAULT_OIDC_CLIENT_ID = "7f8afae4-30e7-4591-b4a8-4fc08d545d1d"
DEFAULT_OIDC_SCOPE = "openid"
DEFAULT_OIDC_ACR_VALUES = "2"
DEFAULT_OIDC_REDIRECT_URI = "https://cloud.o2online.es/sapi/login/oauth"


def config_dir() -> Path:
    """Directory holding the non-secret ``config.toml``."""
    override = os.environ.get("O2CLOUD_CONFIG_DIR")
    base = Path(override) if override else Path(user_config_dir(APP_NAME))
    return base


def state_dir(profile: str = DEFAULT_PROFILE) -> Path:
    """Per-profile state directory (non-secret metadata, caches, sync manifests)."""
    override = os.environ.get("O2CLOUD_STATE_DIR")
    base = Path(override) if override else Path(user_state_dir(APP_NAME))
    return base / profile


def config_file() -> Path:
    return config_dir() / "config.toml"


class AppConfig(BaseSettings):
    """Non-secret runtime configuration for a single profile.

    Field values are resolved with ``O2CLOUD_*`` env precedence by
    ``pydantic-settings``; :func:`load_config` layers the profile TOML *underneath*
    the env so env always wins.
    """

    model_config = SettingsConfigDict(
        env_prefix="O2CLOUD_",
        extra="ignore",
        case_sensitive=False,
    )

    base_url: str = "https://cloud.o2online.es"
    upload_base_url: str = Field(
        default="https://upload.cloud.o2online.es",
        description="Dedicated upload host. The upload action lives at "
        "``<upload_base_url>/sapi/upload?action=save``.",
    )
    user_agent: str = Field(
        default="o2cloud/0.4.0",
        description="App-mimicking User-Agent. TODO(live-capture): replace with the "
        "captured web/app User-Agent from docs/api-reference.md.",
    )
    device_id: str = ""
    request_rate_per_sec: float = 4.0
    default_remote_root: str = "/"
    default_download_dir: str = ""

    # OIDC (non-secret) — see docs/api-reference.md.
    oidc_authorize_base: str = DEFAULT_OIDC_AUTHORIZE_BASE
    oidc_client_name: str = DEFAULT_OIDC_CLIENT_NAME
    oidc_client_id: str = DEFAULT_OIDC_CLIENT_ID
    oidc_scope: str = DEFAULT_OIDC_SCOPE
    oidc_acr_values: str = DEFAULT_OIDC_ACR_VALUES
    oidc_redirect_uri: str = DEFAULT_OIDC_REDIRECT_URI


# Keys a user may read/write via `o2cloud config get/set` (module constant, not a
# pydantic field, so it never leaks into AppConfig.model_fields).
SETTABLE_KEYS: tuple[str, ...] = (
    "base_url",
    "upload_base_url",
    "user_agent",
    "device_id",
    "request_rate_per_sec",
    "default_remote_root",
    "default_download_dir",
    "oidc_authorize_base",
    "oidc_client_name",
    "oidc_client_id",
    "oidc_scope",
    "oidc_acr_values",
    "oidc_redirect_uri",
)


def _read_toml() -> dict[str, Any]:
    path = config_file()
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _read_profile_values(profile: str) -> dict[str, Any]:
    data = _read_toml()
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        return {}
    section = profiles.get(profile, {})
    return dict(section) if isinstance(section, dict) else {}


def load_config(profile: str = DEFAULT_PROFILE) -> AppConfig:
    """Resolve effective config for *profile* (env > TOML > defaults)."""
    toml_values = _read_profile_values(profile)
    # Env-aware base (defaults + O2CLOUD_* env applied by pydantic-settings).
    env_config = AppConfig()

    # Only apply TOML for fields the env did NOT set, so env keeps priority.
    field_names = set(AppConfig.model_fields)
    overrides: dict[str, Any] = {}
    for key, value in toml_values.items():
        if key not in field_names:
            continue
        env_name = f"O2CLOUD_{key.upper()}"
        if os.environ.get(env_name) is not None:
            continue  # env wins
        overrides[key] = value

    if not overrides:
        return env_config
    return env_config.model_copy(update=overrides)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    # string — escape backslashes and quotes for a basic TOML basic-string.
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _dump_toml(data: dict[str, dict[str, Any]]) -> str:
    """Minimal TOML emitter for the ``[profiles.<name>]`` scalar-only structure."""
    lines: list[str] = [
        "# o2cloud non-secret configuration.",
        "# Secrets (username/password/token/cookies) NEVER live here — they are",
        "# stored in the OS keyring or supplied via O2CLOUD_* environment variables.",
        "",
    ]
    for profile, values in data.items():
        lines.append(f"[profiles.{profile}]")
        for key in sorted(values):
            lines.append(f"{key} = {_toml_scalar(values[key])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def get_value(profile: str, key: str) -> Any:
    """Return the effective value of *key* for *profile*."""
    if key not in AppConfig.model_fields:
        from .errors import UsageError

        raise UsageError(f"unknown config key: {key!r}")
    return getattr(load_config(profile), key)


def get_all(profile: str) -> dict[str, Any]:
    """Return every effective config field for *profile* as a plain dict."""
    cfg = load_config(profile)
    return {name: getattr(cfg, name) for name in AppConfig.model_fields}


def set_value(profile: str, key: str, raw_value: str) -> Any:
    """Persist ``key = value`` for *profile* in the TOML store; returns coerced value.

    The value is validated/coerced through :class:`AppConfig` so a bad type (e.g.
    a non-numeric ``request_rate_per_sec``) is rejected before it is written.
    """
    from .errors import UsageError

    if key not in SETTABLE_KEYS:
        raise UsageError(
            f"unknown or read-only config key: {key!r} (settable: {', '.join(SETTABLE_KEYS)})"
        )

    # Coerce/validate through the model so the persisted value has the right type.
    try:
        coerced = getattr(AppConfig.model_validate({key: raw_value}), key)
    except Exception as exc:  # pragma: no cover - defensive
        raise UsageError(f"invalid value for {key!r}: {exc}") from exc

    data = _read_toml()
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    section = profiles.get(profile)
    if not isinstance(section, dict):
        section = {}
    section[key] = coerced
    profiles[profile] = section

    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_toml(profiles), encoding="utf-8")
    return coerced


__all__ = [
    "APP_NAME",
    "DEFAULT_PROFILE",
    "SETTABLE_KEYS",
    "AppConfig",
    "config_dir",
    "state_dir",
    "config_file",
    "load_config",
    "get_value",
    "get_all",
    "set_value",
]
