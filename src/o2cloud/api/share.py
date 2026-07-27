"""SAPI share resource — media-set (album) links.

The memo confirms the ``media/set`` action map (``save|get|delete|
list-media-sets``) and ``GET /sapi/media/set?action=list-media-sets`` →
``data.links[]``, but the exact public-share-link create/revoke request+response
shapes are **not** captured (memo § Albums / shares). Implemented best-effort:

* ``list``   — ``GET /sapi/media/set?action=list-media-sets`` (confirmed shape).
* ``create`` — ``POST /sapi/media/set?action=save`` (best-known; TODO live-capture).
* ``revoke`` — ``POST /sapi/media/set?action=delete`` (best-known; TODO live-capture).
"""

from __future__ import annotations

from typing import Any

from .client import SapiClient
from .models import ShareLink


class ShareApi:
    """Share-link operations over the ``media/set`` resource (best-effort)."""

    def __init__(self, client: SapiClient) -> None:
        self._client = client

    def list(self) -> list[ShareLink]:
        """``GET /sapi/media/set?action=list-media-sets`` → ``data.links[]``."""
        data = self._client.get("/media/set", params={"action": "list-media-sets"})
        raw = data.get("links", []) if isinstance(data, dict) else []
        return [_to_share_link(link) for link in raw]

    def create(self, item_id: str, *, expires_at: str | None = None) -> ShareLink:
        """Create a share/media-set for an item.

        TODO(live-capture): the exact ``media/set?action=save`` body for a
        single-item public share is unconfirmed; this best-known shape sends the
        item id and an optional expiry.
        """
        payload: dict[str, Any] = {"items": [item_id]}
        if expires_at is not None:
            payload["expires"] = expires_at
        data = self._client.post(
            "/media/set", params={"action": "save"}, json_body={"data": payload}
        )
        return _to_share_link(data if isinstance(data, dict) else {}, fallback_item=item_id)

    def revoke(self, share_id: str) -> None:
        """Delete a share/media-set. ``POST /sapi/media/set?action=delete``."""
        self._client.post(
            "/media/set",
            params={"action": "delete"},
            json_body={"data": {"ids": [share_id]}},
        )


def _to_share_link(raw: dict[str, Any], *, fallback_item: str | None = None) -> ShareLink:
    return ShareLink(
        id=str(raw.get("id", raw.get("setid", ""))),
        item_id=str(raw["item_id"]) if raw.get("item_id") is not None else fallback_item,
        url=raw.get("url") or raw.get("link"),
    )


__all__ = ["ShareApi"]
