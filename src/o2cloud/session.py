"""On-disk **non-secret** session metadata (tokens/cookies stay in the keyring).

The state file records only what the CLI needs to decide session freshness
*without* reading a secret from disk: expiry timestamp, account id, base URL, and
the keyring lookup key. The actual token/cookie is fetched from
:class:`o2cloud.secrets.SecretStore` on demand.

State lives under the per-profile state directory
(``<state_dir>/<profile>/session.json``) so switching ``--profile`` cannot reuse
another account's session.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import DEFAULT_PROFILE, state_dir


class SessionMetadata(BaseModel):
    """Non-secret session descriptor persisted to disk.

    Contains **no** secret material — only metadata. ``keyring_key`` names the
    keyring entry (``token`` by default) where the real secret is stored.
    """

    profile: str = DEFAULT_PROFILE
    base_url: str = ""
    account_id: str | None = None
    expires_at: datetime | None = None
    keyring_key: str = "token"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def is_expired(self, *, skew_seconds: int = 60) -> bool:
        """True if the session is past (or within ``skew_seconds`` of) expiry.

        A session with no ``expires_at`` is treated as non-expiring (unknown
        lifetime) — the token itself is validated on first use.
        """
        if self.expires_at is None:
            return False
        now = datetime.now(UTC)
        remaining = (self.expires_at - now).total_seconds()
        return remaining <= skew_seconds


def session_file(profile: str = DEFAULT_PROFILE) -> Path:
    return state_dir(profile) / "session.json"


def load_session(profile: str = DEFAULT_PROFILE) -> SessionMetadata | None:
    """Load session metadata for *profile*, or ``None`` if none is stored."""
    path = session_file(profile)
    if not path.exists():
        return None
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return SessionMetadata.model_validate(raw)


def save_session(meta: SessionMetadata) -> Path:
    """Persist non-secret session metadata; returns the path written."""
    path = session_file(meta.profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return path


def clear_session(profile: str = DEFAULT_PROFILE) -> bool:
    """Remove the session metadata file. Returns ``True`` if a file was removed."""
    path = session_file(profile)
    if path.exists():
        path.unlink()
        return True
    return False


__all__ = [
    "SessionMetadata",
    "session_file",
    "load_session",
    "save_session",
    "clear_session",
]
