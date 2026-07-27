"""SAPI folders resource — list/create/rename/delete + item move.

Endpoints (memo § Mutations / action map):

* list          — ``POST /sapi/media/folder?action=get`` → ``data.folders[]``
* create/rename — ``POST /sapi/media/folder?action=save``
* delete        — ``POST /sapi/media/folder?action=delete`` (soft: ``softdelete``)
* move item     — ``POST /sapi/media/folder?action=add-item`` / ``remove-item``
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .client import SapiClient
from .models import Folder


class FoldersApi:
    """Folder operations over the ``media/folder`` resource."""

    def __init__(self, client: SapiClient) -> None:
        self._client = client

    def list(self, parent_id: str | None = None) -> Sequence[Folder]:
        """List folders. ``POST /sapi/media/folder?action=get`` (body optional).

        The observed endpoint ignores the body and returns the root folder set;
        ``parent_id`` is forwarded when given for backends that honour it.
        """
        body: dict[str, Any] | None = None
        if parent_id is not None:
            body = {"data": {"parent": parent_id}}
        data = self._client.post("/media/folder", params={"action": "get"}, json_body=body)
        folders = data.get("folders", []) if isinstance(data, dict) else []
        return [Folder.model_validate(f) for f in folders]

    def create(self, name: str, *, parent_id: str | None = None) -> Folder:
        """Create a folder. ``POST /sapi/media/folder?action=save``."""
        folder: dict[str, Any] = {"name": name}
        if parent_id is not None:
            folder["parent"] = parent_id
        data = self._client.post(
            "/media/folder", params={"action": "save"}, json_body={"data": folder}
        )
        return Folder.model_validate(data)

    def rename(self, folder_id: str, new_name: str) -> Folder:
        """Rename a folder. ``POST /sapi/media/folder?action=save`` with its id."""
        data = self._client.post(
            "/media/folder",
            params={"action": "save"},
            json_body={"data": {"id": folder_id, "name": new_name}},
        )
        return Folder.model_validate(data)

    def delete(self, folder_id: str, *, permanent: bool = False) -> None:
        """Delete a folder (soft by default → trash; ``permanent`` = hard delete)."""
        action = "delete" if permanent else "softdelete"
        self._client.post(
            "/media/folder",
            params={"action": action},
            json_body={"data": {"folders": [folder_id]}},
        )

    def add_item(self, folder_id: str, item_id: str) -> None:
        """Attach a media item to a folder. ``action=add-item``."""
        self._client.post(
            "/media/folder",
            params={"action": "add-item"},
            json_body={"data": {"id": folder_id, "items": [item_id]}},
        )

    def remove_item(self, folder_id: str, item_id: str) -> None:
        """Detach a media item from a folder. ``action=remove-item``."""
        self._client.post(
            "/media/folder",
            params={"action": "remove-item"},
            json_body={"data": {"id": folder_id, "items": [item_id]}},
        )


__all__ = ["FoldersApi"]
