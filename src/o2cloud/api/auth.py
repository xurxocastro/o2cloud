"""SAPI auth resource — session validation / logout.

The interactive OIDC hand-off and token import live in :mod:`o2cloud.auth.oidc`;
this module owns the SAPI-side session checks once a ``validationKey`` is stored.
There is no server refresh for a ``validationKey`` (memo: "refresh by re-running
login when it 401s"), so :meth:`refresh` is intentionally a re-login prompt.
"""

from __future__ import annotations

from ..errors import AuthError
from .client import SapiClient
from .models import Account


class AuthApi:
    """SAPI session lifecycle over the profile resource."""

    def __init__(self, client: SapiClient) -> None:
        self._client = client

    def whoami(self) -> Account:
        """Validate the stored token and return the account identity.

        ``GET /sapi/profile?action=get`` — a 401 raises :class:`AuthError`; the
        absence of a token is already an :class:`AuthError` from the transport.
        """
        data = self._client.get("/profile", params={"action": "get"})
        return Account.model_validate(data)

    def refresh(self) -> None:
        """A ``validationKey`` cannot be refreshed server-side — re-login instead."""
        raise AuthError(
            "session cannot be refreshed automatically — run 'o2cloud login' again",
            detail={"reason": "validationKey has no refresh endpoint"},
        )

    def logout(self) -> None:
        """SAPI exposes no confirmed logout endpoint; clearing local state suffices.

        The stored ``validationKey`` is removed by the service/command layer; this
        is a no-op server-side (the key simply stops being sent).
        """
        return None


__all__ = ["AuthApi"]
