"""Service layer — orchestrates API calls into user operations.

The API client is dependency-injected so the CLI stays thin and everything is
unit-testable against mocked HTTP. Destination-conflict policy (plan § service):
non-clobbering by default — a pre-existing destination with no override flag is a
``conflict`` (exit 4); ``--force`` overwrites (ok), ``--skip`` intentionally skips
(status ``skipped``, exit 0), ``--rename`` auto-suffixes (ok).
"""

from __future__ import annotations

import enum
import os
from pathlib import Path

from .api.auth import AuthApi
from .api.client import SapiClient
from .api.folders import FoldersApi
from .api.media import MediaApi
from .api.models import Account, MediaItem, Plan, Quota
from .api.quota import QuotaApi
from .api.share import ShareApi
from .api.trash import TrashApi
from .config import AppConfig
from .errors import ConflictError, NotFoundError, O2CloudError, ServerError, UsageError
from .output import BatchItem
from .paths import PathResolver, normalize_remote, remote_basename, remote_join, remote_parent
from .secrets import SecretStore


class ConflictPolicy(enum.Enum):
    """How to treat a pre-existing destination."""

    FAIL = "fail"  # default: report conflict (exit 4)
    FORCE = "force"  # overwrite → ok
    SKIP = "skip"  # intentional skip → status skipped (exit 0)
    RENAME = "rename"  # auto-suffix → ok

    @classmethod
    def from_flags(cls, *, force: bool, skip: bool, rename: bool) -> ConflictPolicy:
        """Derive a policy from mutually-exclusive CLI flags.

        Raises :class:`~o2cloud.errors.UsageError` if more than one is set.
        """
        chosen = [name for name, on in (("force", force), ("skip", skip), ("rename", rename)) if on]
        if len(chosen) > 1:
            from .errors import UsageError

            raise UsageError(f"--{' and --'.join(chosen)} are mutually exclusive")
        if force:
            return cls.FORCE
        if skip:
            return cls.SKIP
        if rename:
            return cls.RENAME
        return cls.FAIL


def _suffixed(name: str) -> str:
    """Return an auto-suffixed variant of a filename for ``--rename``."""
    stem, dot, ext = name.partition(".")
    return f"{stem} (1){dot}{ext}" if dot else f"{name} (1)"


class O2CloudService:
    """High-level operations over the injected SAPI client."""

    def __init__(
        self,
        config: AppConfig,
        secret_store: SecretStore,
        *,
        client: SapiClient | None = None,
    ) -> None:
        self.config = config
        self.secrets = secret_store
        self._client = client if client is not None else SapiClient(config, secret_store)
        self.auth = AuthApi(self._client)
        self.media = MediaApi(self._client)
        self.folders = FoldersApi(self._client)
        self.quota = QuotaApi(self._client)
        self.share = ShareApi(self._client)
        self.trash = TrashApi(self._client)
        self.resolver = PathResolver(self.folders, self.media)

    # --- account ----------------------------------------------------------
    def account(self) -> Account:
        return self.quota.get_account()

    def storage_quota(self) -> Quota:
        return self.quota.get_quota()

    def plan(self) -> list[Plan]:
        return self.quota.get_plan()

    def whoami(self) -> Account:
        return self.auth.whoami()

    # --- listing ----------------------------------------------------------
    def list_dir(self, remote: str, *, detail: bool = True) -> list[MediaItem]:
        """List the entries of a remote folder (folders + media).

        The base media listing is *sparse* (id only, no name). With ``detail`` (the
        default) files are enriched with their name/size via a batch detail call so
        ``ls`` shows filenames; pass ``detail=False`` for the faster raw listing.
        """
        folder_id = self.resolver.resolve_folder(remote)
        # Subfolders surface as folder-typed pseudo media items so ``ls`` shows
        # a unified listing (name + kind), while files come from the media list.
        entries: list[MediaItem] = []
        for folder in self.folders.list(parent_id=folder_id):
            entries.append(
                MediaItem(
                    id=folder.id,
                    name=folder.name,
                    mediatype="folder",
                    folder_id=folder_id,
                    date=folder.date,
                )
            )
        media_items = list(self.media.list(folder_id=folder_id).media)
        if detail:
            self._enrich_media(media_items)
        entries.extend(media_items)
        return entries

    def _enrich_media(self, items: list[MediaItem]) -> None:
        """Fill name/size/url/etag on sparse media items via batch detail.

        Best-effort: groups items by mediatype, one batch detail call per type, and
        merges the result by id. Any per-group failure leaves those items sparse
        rather than failing the whole listing.
        """
        groups: dict[str, list[str]] = {}
        for it in items:
            if it.mediatype and it.mediatype != "folder" and it.id:
                groups.setdefault(it.mediatype, []).append(it.id)
        enriched: dict[str, MediaItem] = {}
        for mtype, ids in groups.items():
            try:
                for det in self.media.get_many(ids, mediatype=mtype):
                    if det.id:
                        enriched[det.id] = det
            except O2CloudError:
                continue  # keep these items sparse
        for it in items:
            d = enriched.get(it.id)
            if d is None:
                continue
            it.name = d.name or it.name
            it.size = d.size if d.size is not None else it.size
            it.url = d.url or it.url
            it.etag = d.etag or it.etag
            it.contenttype = d.contenttype or it.contenttype

    def tree(self, remote: str, *, detail: bool = True) -> list[MediaItem]:
        """Recursively list a remote folder (folders expanded depth-first)."""
        out: list[MediaItem] = []
        self._walk(remote, out, detail=detail)
        return out

    def _walk(self, remote: str, out: list[MediaItem], *, detail: bool = True) -> None:
        for entry in self.list_dir(remote, detail=detail):
            entry.path = remote_join(remote, entry.name or entry.id)
            out.append(entry)
            if entry.mediatype == "folder":
                self._walk(entry.path, out, detail=detail)

    def stat(self, remote: str) -> MediaItem:
        """Return metadata for a remote file or folder."""
        norm = normalize_remote(remote)
        try:
            folder_id = self.resolver.resolve_folder(norm)
        except NotFoundError:
            folder_id = None
        else:
            # It resolved as a folder path.
            if folder_id is not None:
                return MediaItem(id=folder_id, name=remote_basename(norm), mediatype="folder")
        return self.resolver.resolve_item(norm)

    # --- transfers (batch, conflict-aware) --------------------------------
    def upload(
        self, sources: list[Path], remote_dest: str, *, policy: ConflictPolicy
    ) -> list[BatchItem]:
        """Upload one or more local files to a remote folder path."""
        try:
            folder_id = self.resolver.resolve_folder(remote_dest)
        except NotFoundError as exc:
            return [BatchItem.failed(str(s), exc) for s in sources]

        items: list[BatchItem] = []
        for source in sources:
            items.append(self._upload_one(source, remote_dest, folder_id, policy))
        return items

    def _upload_one(
        self, source: Path, remote_dest: str, folder_id: str | None, policy: ConflictPolicy
    ) -> BatchItem:
        target = str(source)
        if not source.exists():
            return BatchItem.failed(target, NotFoundError(f"no such local file: {source}"))
        remote_name = source.name
        remote_path = remote_join(remote_dest, remote_name)
        exists = self._remote_exists(remote_path)
        if exists:
            resolved = self._resolve_conflict(remote_path, remote_name, policy)
            if isinstance(resolved, BatchItem):
                return resolved
            remote_name = resolved
        try:
            result = self.media.upload(source, remote_name=remote_name, folder_id=folder_id)
        except O2CloudError as exc:
            return BatchItem.failed(target, exc)
        return BatchItem.ok(
            target,
            message=f"uploaded → {remote_join(remote_dest, remote_name)}",
            id=result.id,
            etag=result.etag,
        )

    def download(
        self, remotes: list[str], local_dest: Path, *, policy: ConflictPolicy
    ) -> list[BatchItem]:
        """Download one or more remote items to a local destination."""
        items: list[BatchItem] = []
        for remote in remotes:
            items.append(self._download_one(remote, local_dest, policy))
        return items

    def _download_one(self, remote: str, local_dest: Path, policy: ConflictPolicy) -> BatchItem:
        try:
            item = self.resolver.resolve_item(remote)
            # Listings are sparse (no url/name); fetch full detail for the
            # download link. Confirmed: item.url is the direct download link.
            detail = self.media.get(item.id, mediatype=item.mediatype or "file")
        except O2CloudError as exc:
            return BatchItem.failed(remote, exc)

        if not detail.url:
            return BatchItem.failed(remote, ServerError("media detail returned no download url"))

        # The name comes from the SAPI response (untrusted): reduce it to a bare
        # basename so a crafted "../.." or absolute name cannot escape the
        # destination directory (M1), and confine the resolved path to local_dest.
        raw_name = detail.name or item.name or remote_basename(remote)
        name = os.path.basename(raw_name) or remote_basename(remote)
        if name in ("", ".", ".."):
            name = remote_basename(remote)
        if local_dest.is_dir():
            root = local_dest.resolve()
            dest = root / name
            if dest.resolve().parent != root:
                return BatchItem.failed(
                    remote, UsageError("refusing to write outside the destination directory")
                )
        else:
            dest = local_dest
        if dest.exists():
            resolved = self._resolve_conflict(str(dest), name, policy)
            if isinstance(resolved, BatchItem):
                return resolved
            dest = dest.with_name(resolved)
        try:
            response = self._client.download_url(detail.url)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.content)
        except O2CloudError as exc:
            return BatchItem.failed(remote, exc)
        return BatchItem.ok(remote, message=f"downloaded → {dest}")

    # --- conflict helpers -------------------------------------------------
    def _remote_exists(self, remote_path: str) -> bool:
        try:
            self.resolver.resolve_item(remote_path)
        except NotFoundError:
            return False
        return True

    def _resolve_conflict(self, target: str, name: str, policy: ConflictPolicy) -> BatchItem | str:
        """Apply the conflict policy; return a terminal BatchItem or a new name."""
        if policy is ConflictPolicy.FORCE:
            return name
        if policy is ConflictPolicy.SKIP:
            return BatchItem.skipped(target, message="destination exists (--skip)")
        if policy is ConflictPolicy.RENAME:
            return _suffixed(name)
        return BatchItem.conflict(
            target, message="destination exists (use --force/--skip/--rename)"
        )

    # --- single-item mutations -------------------------------------------
    def mkdir(self, remote: str) -> None:
        norm = normalize_remote(remote)
        parent = remote_parent(norm)
        name = remote_basename(norm)
        parent_id = self.resolver.resolve_folder(parent)
        self.folders.create(name, parent_id=parent_id)

    def move(self, src: str, dst: str, *, policy: ConflictPolicy) -> None:
        """Move/rename a remote item between folders (add-item + remove-item)."""
        item = self.resolver.resolve_item(src)
        dst_norm = normalize_remote(dst)
        if self._remote_exists(dst_norm) and policy is ConflictPolicy.FAIL:
            raise ConflictError(f"destination exists: {dst_norm}", detail={"dst": dst_norm})
        dst_folder = self.resolver.resolve_folder(remote_parent(dst_norm))
        src_folder = item.folder_id
        if dst_folder is not None:
            self.folders.add_item(dst_folder, item.id)
        if src_folder is not None and src_folder != dst_folder:
            self.folders.remove_item(src_folder, item.id)

    def copy(self, src: str, dst: str, *, policy: ConflictPolicy) -> None:
        """Server-side copy a remote item into the destination folder."""
        item = self.resolver.resolve_item(src)
        dst_norm = normalize_remote(dst)
        if self._remote_exists(dst_norm) and policy is ConflictPolicy.FAIL:
            raise ConflictError(f"destination exists: {dst_norm}", detail={"dst": dst_norm})
        dst_folder = self.resolver.resolve_folder(remote_parent(dst_norm))
        self.media.copy(item.id, folder_id=dst_folder)

    def remove(self, remote: str, *, permanent: bool = False) -> None:
        item = self.resolver.resolve_item(remote)
        self.media.delete(item.id, permanent=permanent, mediatype=item.mediatype or "file")

    def search(self, query: str) -> list[MediaItem]:
        return list(self.media.search(query))

    def close(self) -> None:
        self._client.close()


__all__ = ["O2CloudService", "ConflictPolicy"]
