"""Secret store: OS keyring primary, ``O2CLOUD_*`` env fallback for headless use.

Secret residency rule: credentials, tokens, and cookies live **only** in the OS
keyring **or** the process environment — never in
ordinary files. This module is the sole gateway to those secrets.

Keyring layout
--------------
Service name is namespaced per profile: ``o2cloud:<profile>``. Within it:

======================  ============================  =========================
 logical secret          keyring key                   env fallback
======================  ============================  =========================
 username (DNI)          ``username``                  ``O2CLOUD_USERNAME``
 password                ``password``                  ``O2CLOUD_PASSWORD``
 SAPI session token      ``token``                     ``O2CLOUD_TOKEN``
 session cookie          ``cookie``                    ``O2CLOUD_COOKIE``
======================  ============================  =========================

Env values take precedence over the keyring so an agent can inject a token
without touching the user's keychain.
"""

from __future__ import annotations

import keyring
from keyring.errors import PasswordDeleteError

_SERVICE_PREFIX = "o2cloud"


def service_name(profile: str) -> str:
    """Keyring service string for *profile* (``o2cloud:<profile>``)."""
    return f"{_SERVICE_PREFIX}:{profile}"


class SecretStore:
    """Per-profile secret accessor over keyring with env fallback.

    Reads resolve env first (``O2CLOUD_<KEY>``) then the keyring. Writes and
    deletes only ever touch the keyring — the environment is read-only from this
    process's point of view.
    """

    _ENV_MAP = {
        "username": "O2CLOUD_USERNAME",
        "password": "O2CLOUD_PASSWORD",
        "token": "O2CLOUD_TOKEN",
        "cookie": "O2CLOUD_COOKIE",
    }

    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.service = service_name(profile)

    # --- generic access ---------------------------------------------------
    def get(self, key: str) -> str | None:
        env_name = self._ENV_MAP.get(key)
        if env_name is not None:
            import os

            env_val = os.environ.get(env_name)
            if env_val:
                return env_val
        return keyring.get_password(self.service, key)

    def set(self, key: str, value: str) -> None:
        keyring.set_password(self.service, key, value)

    def delete(self, key: str) -> bool:
        """Delete a keyring secret. Returns ``True`` if something was removed."""
        try:
            keyring.delete_password(self.service, key)
            return True
        except PasswordDeleteError:
            return False

    # --- typed convenience ------------------------------------------------
    @property
    def username(self) -> str | None:
        return self.get("username")

    @property
    def password(self) -> str | None:
        return self.get("password")

    @property
    def token(self) -> str | None:
        return self.get("token")

    @property
    def cookie(self) -> str | None:
        return self.get("cookie")

    def store_token(self, token: str, *, cookie: str | None = None) -> None:
        """Persist a SAPI session token (and optional cookie) to the keyring."""
        self.set("token", token)
        if cookie is not None:
            self.set("cookie", cookie)

    def clear(self) -> None:
        """Remove every keyring secret for this profile (env is untouched)."""
        for key in self._ENV_MAP:
            self.delete(key)


__all__ = ["SecretStore", "service_name"]
