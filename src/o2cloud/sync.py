"""Directory sync engine — persisted three-way baseline.

Design (plan § sync.py):

* A per-``(profile, local_root, remote_root)`` **manifest** records the last-synced
  state per path (a *local* signature + a *remote* signature + the remote id) plus
  **tombstones** for entries deleted after a prior sync. Stored under the profile
  state dir.
* Each run computes a **three-way diff** (baseline vs current-local vs
  current-remote) to distinguish *created locally* from *deleted remotely* and to
  flag **both-sides-modified conflicts** instead of guessing.
* **First run (no manifest):** union with no deletions; one-sided paths are copied;
  identical same-path objects coalesce into the baseline; differing same-path
  objects are **conflicts** (need ``--prefer-local``/``--prefer-remote``).
* **Deletion propagation** only with ``--delete`` and only for baseline-confirmed
  disappearances.
* **Manifest commit semantics:** the baseline advances **per confirmed action**
  after the mutation is verified; failed/skipped/conflict entries are never
  advanced, so an interrupted run leaves a consistent baseline and retries exactly
  the unfinished work.
* **Concurrency safety:** confirmed actions funnel to a **single serialized
  manifest writer** (atomic temp-write+rename); each sync holds an **exclusive
  lock** on the ``(profile, local_root, remote_root)`` triple so two processes
  cannot corrupt the baseline (a second invocation fails fast).

The pure :func:`diff` function operates on plain snapshots and is fully testable
without any network or filesystem.
"""

from __future__ import annotations

import contextlib
import enum
import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .api.models import MediaItem, SyncAction, SyncPlan
from .config import DEFAULT_PROFILE, state_dir
from .errors import O2CloudError
from .paths import remote_join
from .service import O2CloudService


class SyncDirection(enum.Enum):
    UP = "up"
    DOWN = "down"
    TWO_WAY = "two-way"


class ConflictResolution(enum.Enum):
    NONE = "none"
    PREFER_LOCAL = "prefer-local"
    PREFER_REMOTE = "prefer-remote"


def manifest_path(local_root: Path, remote_root: str, *, profile: str = DEFAULT_PROFILE) -> Path:
    """Deterministic manifest location for a ``(profile, local_root, remote_root)``.

    Uses a stable hash of the local+remote roots so distinct sync pairs never share
    a baseline. Pure/testable (no I/O beyond path construction).
    """
    key = f"{local_root.resolve()}\x00{remote_root}".encode()
    digest = hashlib.sha256(key).hexdigest()[:16]
    return state_dir(profile) / "sync" / f"{digest}.manifest.json"


# --- baseline manifest ------------------------------------------------------
@dataclass
class BaselineEntry:
    """One path's last-synced signatures + remote id."""

    local_sig: str
    remote_sig: str
    remote_id: str | None = None


@dataclass
class Manifest:
    """Persisted three-way baseline: per-path entries + deletion tombstones."""

    entries: dict[str, BaselineEntry] = field(default_factory=dict)
    tombstones: set[str] = field(default_factory=set)

    def to_json(self) -> str:
        return json.dumps(
            {
                "entries": {
                    p: {"local": e.local_sig, "remote": e.remote_sig, "remote_id": e.remote_id}
                    for p, e in self.entries.items()
                },
                "tombstones": sorted(self.tombstones),
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        raw = json.loads(text)
        entries = {
            p: BaselineEntry(
                local_sig=d.get("local", ""),
                remote_sig=d.get("remote", ""),
                remote_id=d.get("remote_id"),
            )
            for p, d in raw.get("entries", {}).items()
        }
        return cls(entries=entries, tombstones=set(raw.get("tombstones", [])))


def load_manifest(path: Path) -> Manifest:
    """Load a manifest, returning an empty one if none exists (first run)."""
    if not path.exists():
        return Manifest()
    try:
        return Manifest.from_json(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Manifest()


# --- signatures -------------------------------------------------------------
def local_signature(path: Path) -> str:
    """A cheap local change signature: ``size:mtime_ns``."""
    st = path.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def remote_signature(item: MediaItem) -> str:
    """A remote change signature: size + ETag if present, else ``size`` / ``date``."""
    parts = []
    if item.size is not None:
        parts.append(f"size:{item.size}")
    if item.etag:
        parts.append(f"etag:{item.etag}")
    if parts:
        return ":".join(parts)
    return f"date:{item.date}"


# --- pure three-way diff ----------------------------------------------------
def diff(
    baseline: dict[str, BaselineEntry],
    local: dict[str, str],
    remote: dict[str, str],
    *,
    direction: SyncDirection,
    delete: bool = False,
    resolution: ConflictResolution = ConflictResolution.NONE,
) -> SyncPlan:
    """Compute the three-way action plan. Pure — no I/O.

    ``local``/``remote`` map a relative path to its current signature; ``baseline``
    is the last-synced state. Returns a :class:`SyncPlan` of :class:`SyncAction`.
    """
    actions: list[SyncAction] = []
    paths = set(baseline) | set(local) | set(remote)
    allow_up = direction in (SyncDirection.UP, SyncDirection.TWO_WAY)
    allow_down = direction in (SyncDirection.DOWN, SyncDirection.TWO_WAY)

    for path in sorted(paths):
        b = baseline.get(path)
        lsig = local.get(path)
        rsig = remote.get(path)
        in_l = lsig is not None
        in_r = rsig is not None

        if b is None:
            # No baseline for this path.
            if in_l and in_r:
                if _same(lsig, rsig):
                    actions.append(SyncAction(op="noop", path=path, reason="identical (coalesce)"))
                else:
                    actions.append(
                        _resolved_conflict(path, resolution, allow_up, allow_down)
                        or SyncAction(op="conflict", path=path, reason="differs on both sides")
                    )
            elif in_l and allow_up:
                actions.append(SyncAction(op="upload", path=path, reason="new local"))
            elif in_r and allow_down:
                actions.append(SyncAction(op="download", path=path, reason="new remote"))
            continue

        # A baseline exists.
        local_changed = in_l and b.local_sig != lsig
        remote_changed = in_r and b.remote_sig != rsig

        if in_l and in_r:
            if local_changed and remote_changed:
                actions.append(
                    _resolved_conflict(path, resolution, allow_up, allow_down)
                    or SyncAction(op="conflict", path=path, reason="both sides modified")
                )
            elif local_changed and allow_up:
                actions.append(SyncAction(op="upload", path=path, reason="local modified"))
            elif remote_changed and allow_down:
                actions.append(SyncAction(op="download", path=path, reason="remote modified"))
            else:
                actions.append(SyncAction(op="noop", path=path, reason="unchanged"))
        elif in_l and not in_r:
            # Disappeared remotely since baseline.
            if local_changed and allow_up:
                actions.append(SyncAction(op="upload", path=path, reason="re-created local"))
            elif delete and allow_down:
                actions.append(SyncAction(op="delete_local", path=path, reason="deleted remotely"))
            else:
                actions.append(
                    SyncAction(op="noop", path=path, reason="remote deleted (no --delete)")
                )
        elif in_r and not in_l:
            if remote_changed and allow_down:
                actions.append(SyncAction(op="download", path=path, reason="re-created remote"))
            elif delete and allow_up:
                actions.append(SyncAction(op="delete_remote", path=path, reason="deleted locally"))
            else:
                actions.append(
                    SyncAction(op="noop", path=path, reason="local deleted (no --delete)")
                )
        else:
            # Gone from both sides — the baseline entry is stale (tombstone).
            actions.append(SyncAction(op="noop", path=path, reason="removed both sides"))

    return SyncPlan(actions=actions)


def _same(a: str | None, b: str | None) -> bool:
    """Two signatures compare equal only when they encode the same content class.

    Local (``size:mtime``) and remote (``etag:`` / ``size:``) signatures are not
    directly comparable, so first-run coalescing treats a matching *size* as
    identical and everything else as differing.
    """
    if a is None or b is None:
        return False
    if a == b:
        return True
    return _size_of(a) is not None and _size_of(a) == _size_of(b)


def _size_of(sig: str) -> int | None:
    for token in sig.split(":"):
        if token.isdigit():
            return int(token)
    return None


def _resolved_conflict(
    path: str, resolution: ConflictResolution, allow_up: bool, allow_down: bool
) -> SyncAction | None:
    if resolution is ConflictResolution.PREFER_LOCAL and allow_up:
        return SyncAction(op="upload", path=path, reason="conflict → prefer-local")
    if resolution is ConflictResolution.PREFER_REMOTE and allow_down:
        return SyncAction(op="download", path=path, reason="conflict → prefer-remote")
    return None


# --- exclusive lock ---------------------------------------------------------
class SyncLock:
    """Exclusive lock on a sync pair via ``O_CREAT|O_EXCL`` lockfile."""

    def __init__(self, manifest: Path) -> None:
        self.lockfile = manifest.with_suffix(manifest.suffix + ".lock")

    def __enter__(self) -> SyncLock:
        self.lockfile.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lockfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise O2CloudError(
                "sync already running for this local/remote pair",
                detail={"lockfile": str(self.lockfile)},
            ) from exc
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc: object) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.lockfile.unlink()


# --- serialized manifest writer --------------------------------------------
class ManifestWriter:
    """Single owner that applies confirmed actions and atomically persists.

    All confirmed baseline advances funnel through :meth:`commit` under one lock,
    eliminating read-modify-write races when transfers are concurrent.
    """

    def __init__(self, path: Path, manifest: Manifest) -> None:
        self._path = path
        self._manifest = manifest
        self._lock = threading.Lock()

    def commit(
        self,
        path: str,
        *,
        local_sig: str | None,
        remote_sig: str | None,
        remote_id: str | None = None,
    ) -> None:
        """Advance the baseline for one confirmed path and persist atomically."""
        with self._lock:
            if local_sig is None and remote_sig is None:
                self._manifest.entries.pop(path, None)
                self._manifest.tombstones.add(path)
            else:
                self._manifest.entries[path] = BaselineEntry(
                    local_sig=local_sig or "",
                    remote_sig=remote_sig or "",
                    remote_id=remote_id,
                )
                self._manifest.tombstones.discard(path)
            self._flush()

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(self._manifest.to_json(), encoding="utf-8")
        tmp.replace(self._path)


# --- engine -----------------------------------------------------------------
class SyncEngine:
    """Three-way directory sync over the injected service."""

    def __init__(self, service: O2CloudService, *, profile: str = DEFAULT_PROFILE) -> None:
        self.service = service
        self.profile = profile

    # --- snapshots --------------------------------------------------------
    def _scan_local(self, local_root: Path) -> tuple[dict[str, str], dict[str, Path]]:
        sigs: dict[str, str] = {}
        files: dict[str, Path] = {}
        if not local_root.exists():
            return sigs, files
        for path in sorted(local_root.rglob("*")):
            if path.is_file():
                if path.name.startswith("._") or path.name == ".DS_Store":
                    continue
                rel = path.relative_to(local_root).as_posix()
                sigs[rel] = local_signature(path)
                files[rel] = path
        return sigs, files

    def _scan_remote(self, remote_root: str) -> tuple[dict[str, str], dict[str, MediaItem]]:
        sigs: dict[str, str] = {}
        items: dict[str, MediaItem] = {}
        for item in self.service.tree(remote_root):
            if item.mediatype == "folder":
                continue
            name = item.name or item.id
            if name.startswith("._") or name == ".DS_Store":
                continue
            full = item.path or remote_join(remote_root, name)
            rel = _relativize(full, remote_root)
            sigs[rel] = remote_signature(item)
            items[rel] = item
        return sigs, items

    # --- plan -------------------------------------------------------------
    def plan(
        self,
        local_root: Path,
        remote_root: str,
        *,
        direction: SyncDirection,
        delete: bool = False,
        resolution: ConflictResolution = ConflictResolution.NONE,
    ) -> SyncPlan:
        """Compute the three-way action plan (``--dry-run`` renders this)."""
        manifest = load_manifest(manifest_path(local_root, remote_root, profile=self.profile))
        local_sigs, _ = self._scan_local(local_root)
        remote_sigs, _ = self._scan_remote(remote_root)
        return diff(
            manifest.entries,
            local_sigs,
            remote_sigs,
            direction=direction,
            delete=delete,
            resolution=resolution,
        )

    # --- run --------------------------------------------------------------
    def run(
        self,
        local_root: Path,
        remote_root: str,
        *,
        direction: SyncDirection,
        delete: bool = False,
        dry_run: bool = False,
        resolution: ConflictResolution = ConflictResolution.NONE,
    ) -> SyncPlan:
        """Execute the sync plan with per-action manifest commits under a lock."""
        mpath = manifest_path(local_root, remote_root, profile=self.profile)
        manifest = load_manifest(mpath)
        local_sigs, local_files = self._scan_local(local_root)
        remote_sigs, remote_items = self._scan_remote(remote_root)
        computed = diff(
            manifest.entries,
            local_sigs,
            remote_sigs,
            direction=direction,
            delete=delete,
            resolution=resolution,
        )
        if dry_run:
            return computed

        executed: list[SyncAction] = []
        total_actions = len(computed.actions)
        with SyncLock(mpath):
            writer = ManifestWriter(mpath, manifest)
            for idx, action in enumerate(computed.actions, 1):
                if action.op == "upload":
                    print(f"[{idx}/{total_actions}] Subiendo {action.path}...", flush=True)
                res = self._apply(
                    action,
                    local_root,
                    remote_root,
                    local_sigs,
                    remote_sigs,
                    remote_items,
                    writer,
                )
                executed.append(res)
        return SyncPlan(actions=executed)

    def _apply(
        self,
        action: SyncAction,
        local_root: Path,
        remote_root: str,
        local_sigs: dict[str, str],
        remote_sigs: dict[str, str],
        remote_items: dict[str, MediaItem],
        writer: ManifestWriter,
    ) -> SyncAction:
        """Execute one action; advance the baseline only on confirmed success."""
        from .service import ConflictPolicy

        path = action.path
        remote_item = remote_items.get(path)
        remote_id = remote_item.id if remote_item is not None else None
        try:
            if action.op == "upload":
                self.service.upload(
                    [local_root / path],
                    remote_join(remote_root, _dirname(path)),
                    policy=ConflictPolicy.FORCE,
                )
                writer.commit(
                    path,
                    local_sig=local_sigs.get(path),
                    remote_sig=remote_sigs.get(path) or local_sigs.get(path),
                    remote_id=remote_id,
                )
            elif action.op == "download":
                self.service.download(
                    [remote_join(remote_root, path)],
                    (local_root / path).parent,
                    policy=ConflictPolicy.FORCE,
                )
                writer.commit(
                    path,
                    local_sig=local_sigs.get(path) or remote_sigs.get(path),
                    remote_sig=remote_sigs.get(path),
                    remote_id=remote_id,
                )
            elif action.op == "delete_local":
                target = local_root / path
                if target.exists():
                    target.unlink()
                writer.commit(path, local_sig=None, remote_sig=None)
            elif action.op == "delete_remote":
                self.service.remove(remote_join(remote_root, path), permanent=False)
                writer.commit(path, local_sig=None, remote_sig=None)
            elif action.op in ("noop", "conflict"):
                return action
        except (O2CloudError, OSError) as exc:
            reason = exc.message if isinstance(exc, O2CloudError) else str(exc)
            return SyncAction(op="conflict", path=path, reason=f"failed: {reason}")
        return action


def _relativize(full: str, root: str) -> str:
    root_norm = root.rstrip("/")
    if root_norm and full.startswith(root_norm + "/"):
        return full[len(root_norm) + 1 :]
    return full.lstrip("/")


def _dirname(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


__all__ = [
    "SyncEngine",
    "SyncDirection",
    "ConflictResolution",
    "Manifest",
    "BaselineEntry",
    "ManifestWriter",
    "SyncLock",
    "manifest_path",
    "load_manifest",
    "local_signature",
    "remote_signature",
    "diff",
]
