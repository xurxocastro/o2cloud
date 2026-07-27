"""SAPI trash resource — list / restore / empty.

The memo confirms soft-delete (``action=softdelete``) populates the trash and
that ``get-storage-space`` reports ``softdeleted`` bytes, but the dedicated trash
list/restore/empty request+response params are still **TBD** (memo § Mutations:
"Trash … restore/empty — params TBD"). Implemented here as the best-known version
behind clearly-marked ``TODO(live-capture)`` markers:

* ``list``    — media listing filtered to soft-deleted items (best-effort).
* ``empty``   — hard-delete every soft-deleted item via the confirmed media
                delete endpoint.
* ``restore`` — best-guess ``media/trash?action=restore`` (undocumented action).
"""

from __future__ import annotations

from typing import Any

from .client import SapiClient
from .models import MediaItem, TrashItem


class TrashApi:
    """Trash operations (best-effort; see module docstring for the gaps)."""

    def __init__(self, client: SapiClient) -> None:
        self._client = client

    def list(self, *, limit: int = 500) -> list[TrashItem]:
        """List soft-deleted items.

        TODO(live-capture): confirm the dedicated ``media/trash`` list endpoint.
        Best-known version: request the media listing with ``softdeleted=true``
        and surface the soft-deleted entries.
        """
        data = self._client.get(
            "/media", params={"action": "get", "limit": limit, "softdeleted": "true"}
        )
        raw = data.get("media", []) if isinstance(data, dict) else []
        items = [MediaItem.model_validate(m) for m in raw]
        trashed = [m for m in items if _is_softdeleted(m)]
        return [
            TrashItem(id=m.id, name=m.name, mediatype=m.mediatype, original_path=m.path)
            for m in trashed
        ]

    def restore(self, item_id: str) -> None:
        """Restore a soft-deleted item.

        TODO(live-capture): the restore action/params are undocumented (no
        ``restore`` appears in the media action map). Best-guess request below;
        confirm against one live capture before relying on it.
        """
        self._client.post(
            "/media/trash",
            params={"action": "restore"},
            json_body={"data": {"ids": [item_id]}},
        )

    def empty(self) -> int:
        """Permanently delete every soft-deleted item; returns the count removed.

        Uses the **confirmed** hard-delete endpoint per item rather than an
        unconfirmed bulk ``empty`` action, so behaviour is well-defined.
        """
        trashed = self.list()
        removed = 0
        for item in trashed:
            self._client.post(
                "/media/file",
                params={"action": "delete"},
                json_body={"data": {"files": [item.id]}},
            )
            removed += 1
        return removed


def _is_softdeleted(item: MediaItem) -> bool:
    """Heuristic: SAPI marks soft-deleted items with a non-``U`` status flag."""
    extra: dict[str, Any] = getattr(item, "model_extra", None) or {}
    if extra.get("softdeleted") or extra.get("deleted"):
        return True
    status = (item.status or "").upper()
    return status in {"D", "S", "SOFTDELETED", "DELETED"}


__all__ = ["TrashApi", "_is_softdeleted"]
