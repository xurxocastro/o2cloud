"""SAPI media/files resource — list/detail/upload/download/delete/copy.

Endpoints (memo § Read endpoints / Mutations):

* list     — ``GET /sapi/media?action=get&limit=N`` → ``data{media[], more}``
* detail   — ``POST /sapi/media/file?action=get {data:{files:[{id}]}}``  (best-known)
* upload   — ``POST {UPLOAD_HOST}?action=save`` (multipart) then poll
             ``POST /sapi/media?action=get-validation-status {data:{ids:[{id}]}}``
* delete   — ``POST /sapi/media/file?action=delete`` (soft: ``softdelete``)
* copy     — ``POST /sapi/media/file?action=copy`` (server-side)
* export   — ``action=export`` on ``/sapi/media/{file,picture,video}`` → signed link
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .client import SapiClient
from .models import MediaItem, MediaListing, UploadResult, ValidationEntry

# Media-type → per-type SAPI sub-resource and JSON payload key for detail/export calls.
_TYPE_RESOURCE = {
    "file": "file",
    "picture": "picture",
    "video": "video",
    "audio": "audio",
}
_TYPE_KEY = {
    "file": "files",
    "picture": "pictures",
    "video": "videos",
    "audio": "audios",
}


class MediaApi:
    """Media/file operations over the ``media`` resource."""

    def __init__(self, client: SapiClient) -> None:
        self._client = client

    # --- reads ------------------------------------------------------------
    def list(self, *, limit: int = 100, folder_id: str | None = None) -> MediaListing:
        """``GET /sapi/media?action=get&limit=N`` → sparse ``{media[], more}``.

        ``folder_id`` is forwarded when given; the base listing is account-wide
        and sparse (per-item detail requires :meth:`get`).
        """
        params: dict[str, Any] = {"action": "get", "limit": limit}
        if folder_id is not None:
            params["folder"] = folder_id
        data = self._client.get("/media", params=params)
        return MediaListing.model_validate(data)

    def get(self, item_id: str, *, mediatype: str = "file") -> MediaItem:
        """Fetch a single item's full metadata (CONFIRMED live 2026-07-22)."""
        resource = _TYPE_RESOURCE.get(mediatype, "file")
        key = _TYPE_KEY.get(mediatype, "files")
        data = self._client.post(
            f"/media/{resource}",
            params={"action": "get"},
            json_body={"data": {key: [{"id": item_id}]}},
        )
        # The detail endpoint may wrap the item in a list/keyed object; normalise.
        item = _first_item(data, item_id)
        return MediaItem.model_validate(item)

    def get_many(self, item_ids: Sequence[str], *, mediatype: str = "file") -> Sequence[MediaItem]:
        """Batch-fetch full metadata for several items of the **same** mediatype."""
        ids = [i for i in item_ids if i]
        if not ids:
            return []
        resource = _TYPE_RESOURCE.get(mediatype, "file")
        key = _TYPE_KEY.get(mediatype, "files")
        data = self._client.post(
            f"/media/{resource}",
            params={"action": "get"},
            json_body={"data": {key: [{"id": i} for i in ids]}},
        )
        raw = (data.get(key) or data.get("files")) if isinstance(data, dict) else None
        return [MediaItem.model_validate(x) for x in (raw or [])]

    # --- upload choreography ---------------------------------------------
    def upload(
        self,
        source: Path,
        *,
        remote_name: str | None = None,
        folder_id: str | None = None,
    ) -> UploadResult:
        """Upload a file, then confirm it via the validation-status poll.

        1. ``POST {UPLOAD_HOST}?action=save`` (multipart) → ``{success,id,etag,…}``.
        2. ``POST /sapi/media?action=get-validation-status`` to confirm the new
           id passed virus/processing checks.
        """
        extra: dict[str, Any] = {}
        if folder_id is not None:
            extra["folder"] = folder_id
        raw = self._client.upload_save(
            source, remote_name=remote_name, extra_metadata=extra or None
        )
        result = UploadResult.model_validate(raw)
        if result.id:
            # Best-effort post-upload confirmation; a non-fatal poll error does
            # not undo the stored bytes, so it is surfaced by the caller instead.
            self.validation_status([result.id])
        return result

    def validation_status(self, ids: Sequence[str]) -> Sequence[ValidationEntry]:
        """``POST /sapi/media?action=get-validation-status {data:{ids:[{id}]}}``."""
        body = {"data": {"ids": [{"id": i} for i in ids]}}
        data = self._client.post(
            "/media", params={"action": "get-validation-status"}, json_body=body
        )
        entries = data.get("ids", []) if isinstance(data, dict) else []
        return [ValidationEntry.model_validate(e) for e in entries]

    # --- mutations --------------------------------------------------------
    def delete(self, item_id: str, *, permanent: bool = False, mediatype: str = "file") -> None:
        """Delete a media item (soft by default → trash; ``permanent`` = hard).

        ``POST /sapi/media/file?action=delete`` (or ``softdelete``) with
        ``{data:{files:[id]}}``.
        """
        resource = _TYPE_RESOURCE.get(mediatype, "file")
        action = "delete" if permanent else "softdelete"
        self._client.post(
            f"/media/{resource}",
            params={"action": action},
            json_body={"data": {"files": [item_id]}},
        )

    def copy(self, item_id: str, *, folder_id: str | None = None) -> MediaItem:
        """Server-side copy. ``POST /sapi/media/file?action=copy``.

        No download+reupload needed (memo). Returns the new item metadata.
        """
        body: dict[str, Any] = {"data": {"files": [item_id]}}
        if folder_id is not None:
            body["data"]["folder"] = folder_id
        data = self._client.post("/media/file", params={"action": "copy"}, json_body=body)
        item = _first_item(data, item_id)
        return MediaItem.model_validate(item)

    # --- download link ----------------------------------------------------
    def export_link(self, item_id: str, *, mediatype: str = "file") -> str:
        """Return a signed download link for an item (``action=export``).

        TODO(live-capture): the exact ``export`` request/response params are
        unconfirmed (a guessed ``?id=`` returned the SPA shell). The best-known
        shape is a POST with ``{data:{files:[{id}]}}`` returning a link under a
        ``link``/``url``/``getlink`` key; adjust once one live capture lands.
        """
        resource = _TYPE_RESOURCE.get(mediatype, "file")
        data = self._client.post(
            f"/media/{resource}",
            params={"action": "export"},
            json_body={"data": {"files": [{"id": item_id}]}},
        )
        for key in ("link", "url", "getlink", "exportlink"):
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, str) and value:
                return value
        item = _first_item(data, item_id)
        for key in ("link", "url", "getlink"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
        from ..errors import ServerError

        raise ServerError(
            "no download link in export response",
            detail={"item_id": item_id, "keys": list(data) if isinstance(data, dict) else []},
        )

    # --- search (client-side fallback) -----------------------------------
    def search(self, query: str, *, limit: int = 500) -> Sequence[MediaItem]:
        """Client-side search fallback (memo: no server search endpoint yet).

        Filters a media listing by a case-insensitive substring over the item
        name/id. This is the documented fallback rule, not a server call.
        """
        needle = query.casefold()
        listing = self.list(limit=limit)
        out: list[MediaItem] = []
        for item in listing.media:
            haystacks = [item.name or "", item.id, item.path or ""]
            if any(needle in h.casefold() for h in haystacks):
                out.append(item)
        return out


def _first_item(data: Any, item_id: str) -> dict[str, Any]:
    """Best-effort extraction of a single item dict from a detail/copy response."""
    if isinstance(data, dict):
        for key in ("files", "media", "items"):
            seq = data.get(key)
            if isinstance(seq, list) and seq and isinstance(seq[0], dict):
                return seq[0]
        if "id" in data:
            return data
    return {"id": item_id}


__all__ = ["MediaApi"]
