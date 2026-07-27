"""Remote path ↔ Funambol folder-id mapping and normalization.

The pure normalization helpers (``normalize_remote`` / ``remote_basename`` /
``remote_join``) are network-free and unit-testable. :class:`PathResolver` walks
the live folder listing to turn a normalized remote path into a concrete folder
id (``None`` = account root), and locates a media item by its remote basename.

Folder listing returns folder **names** (memo § Read endpoints), so folder-path
resolution is exact. Media listings are **sparse** (no name until a detail call),
so item-by-path resolution is best-effort and documented as such.
"""

from __future__ import annotations

import posixpath

from .api.folders import FoldersApi
from .api.media import MediaApi
from .api.models import Folder, MediaItem
from .errors import NotFoundError


def normalize_remote(path: str) -> str:
    """Normalize a remote path to an absolute, POSIX-style, collapsed form.

    ``ls foo/../bar`` → ``/bar``; trailing slashes are stripped (except root).
    Remote paths are always POSIX regardless of the host OS.
    """
    if not path or path == "/":
        return "/"
    text = path.replace("\\", "/")
    if not text.startswith("/"):
        text = "/" + text
    collapsed = posixpath.normpath(text)
    return collapsed if collapsed != "." else "/"


def remote_basename(path: str) -> str:
    """Return the final component of a normalized remote path."""
    return posixpath.basename(normalize_remote(path).rstrip("/")) or "/"


def remote_parent(path: str) -> str:
    """Return the parent of a normalized remote path (root's parent is root)."""
    norm = normalize_remote(path)
    if norm == "/":
        return "/"
    parent = posixpath.dirname(norm)
    return parent or "/"


def remote_join(base: str, *parts: str) -> str:
    """Join remote path components and normalize the result."""
    joined = posixpath.join(normalize_remote(base), *parts)
    return normalize_remote(joined)


def split_segments(path: str) -> list[str]:
    """Return the non-empty path segments of a normalized remote path."""
    norm = normalize_remote(path)
    return [s for s in norm.split("/") if s]


class PathResolver:
    """Resolve normalized remote paths to Funambol folder ids / media items."""

    def __init__(self, folders: FoldersApi, media: MediaApi) -> None:
        self._folders = folders
        self._media = media

    def resolve_folder(self, path: str) -> str | None:
        """Resolve a folder path to its id (``None`` = account root).

        Walks one folder level at a time, forwarding the parent id to the folder
        listing. Raises :class:`NotFoundError` if any segment is missing.
        """
        segments = split_segments(path)
        parent_id: str | None = None
        for seg in segments:
            folder = self._find_child(seg, parent_id)
            if folder is None:
                raise NotFoundError(
                    f"no such remote folder: {seg!r}",
                    detail={"path": normalize_remote(path), "missing": seg},
                )
            parent_id = folder.id
        return parent_id

    def _find_child(self, name: str, parent_id: str | None) -> Folder | None:
        for folder in self._folders.list(parent_id=parent_id):
            if folder.name == name:
                return folder
        return None

    def resolve_item(self, path: str, *, limit: int = 500) -> MediaItem:
        """Best-effort locate a media item by its remote basename.

        TODO(live-capture): media listings are sparse (no name), so this matches
        on any name/path metadata already present and falls back to the item id.
        A confirmed per-folder named listing would make this exact.
        """
        target = remote_basename(path)
        listing = self._media.list(limit=limit)
        for item in listing.media:
            if item.name == target or item.id == target:
                return item
            if item.path and remote_basename(item.path) == target:
                return item
        raise NotFoundError(
            f"no such remote item: {target!r}",
            detail={"path": normalize_remote(path)},
        )


__all__ = [
    "normalize_remote",
    "remote_basename",
    "remote_parent",
    "remote_join",
    "split_segments",
    "PathResolver",
]
