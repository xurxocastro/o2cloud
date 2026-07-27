"""Three-way sync diff, manifest persistence, and the exclusive lock (no network)."""

from __future__ import annotations

import pytest

from o2cloud.errors import O2CloudError
from o2cloud.sync import (
    BaselineEntry,
    ConflictResolution,
    Manifest,
    ManifestWriter,
    SyncDirection,
    SyncLock,
    diff,
    manifest_path,
)


def _ops(plan) -> dict[str, str]:
    return {a.path: a.op for a in plan.actions}


def test_first_run_new_local_uploads() -> None:
    plan = diff({}, {"a.txt": "size:1"}, {}, direction=SyncDirection.TWO_WAY)
    assert _ops(plan) == {"a.txt": "upload"}


def test_first_run_new_remote_downloads() -> None:
    plan = diff({}, {}, {"a.txt": "etag:x"}, direction=SyncDirection.TWO_WAY)
    assert _ops(plan) == {"a.txt": "download"}


def test_first_run_identical_size_coalesces_to_noop() -> None:
    plan = diff({}, {"a.txt": "10:99"}, {"a.txt": "size:10"}, direction=SyncDirection.TWO_WAY)
    assert _ops(plan) == {"a.txt": "noop"}


def test_first_run_differing_is_conflict() -> None:
    plan = diff({}, {"a.txt": "size:10"}, {"a.txt": "size:20"}, direction=SyncDirection.TWO_WAY)
    assert _ops(plan) == {"a.txt": "conflict"}


def test_baseline_local_modified_uploads() -> None:
    baseline = {"a.txt": BaselineEntry(local_sig="10:1", remote_sig="etag:x")}
    plan = diff(baseline, {"a.txt": "10:2"}, {"a.txt": "etag:x"}, direction=SyncDirection.TWO_WAY)
    assert _ops(plan) == {"a.txt": "upload"}


def test_baseline_remote_modified_downloads() -> None:
    baseline = {"a.txt": BaselineEntry(local_sig="10:1", remote_sig="etag:x")}
    plan = diff(baseline, {"a.txt": "10:1"}, {"a.txt": "etag:y"}, direction=SyncDirection.TWO_WAY)
    assert _ops(plan) == {"a.txt": "download"}


def test_baseline_both_modified_is_conflict() -> None:
    baseline = {"a.txt": BaselineEntry(local_sig="10:1", remote_sig="etag:x")}
    plan = diff(baseline, {"a.txt": "10:2"}, {"a.txt": "etag:y"}, direction=SyncDirection.TWO_WAY)
    assert _ops(plan) == {"a.txt": "conflict"}


def test_conflict_resolution_prefers_local() -> None:
    baseline = {"a.txt": BaselineEntry(local_sig="10:1", remote_sig="etag:x")}
    plan = diff(
        baseline,
        {"a.txt": "10:2"},
        {"a.txt": "etag:y"},
        direction=SyncDirection.TWO_WAY,
        resolution=ConflictResolution.PREFER_LOCAL,
    )
    assert _ops(plan) == {"a.txt": "upload"}


def test_deletion_propagation_requires_delete_flag() -> None:
    baseline = {"a.txt": BaselineEntry(local_sig="10:1", remote_sig="etag:x")}
    # Disappeared locally, unchanged remotely, no --delete → noop.
    plan = diff(baseline, {}, {"a.txt": "etag:x"}, direction=SyncDirection.TWO_WAY)
    assert _ops(plan) == {"a.txt": "noop"}
    # With --delete → delete_remote.
    plan2 = diff(baseline, {}, {"a.txt": "etag:x"}, direction=SyncDirection.TWO_WAY, delete=True)
    assert _ops(plan2) == {"a.txt": "delete_remote"}


def test_direction_up_ignores_remote_only_changes() -> None:
    plan = diff({}, {}, {"a.txt": "etag:x"}, direction=SyncDirection.UP)
    # A remote-only new file is not downloaded in --up mode.
    assert plan.actions == []


def test_direction_down_ignores_local_only_changes() -> None:
    plan = diff({}, {"a.txt": "10:1"}, {}, direction=SyncDirection.DOWN)
    assert plan.actions == []


def test_manifest_round_trip() -> None:
    m = Manifest(
        entries={"a": BaselineEntry(local_sig="1", remote_sig="2", remote_id="id1")},
        tombstones={"b"},
    )
    restored = Manifest.from_json(m.to_json())
    assert restored.entries["a"].remote_id == "id1"
    assert restored.tombstones == {"b"}


def test_manifest_writer_advances_and_tombstones(tmp_path) -> None:
    path = tmp_path / "m.json"
    writer = ManifestWriter(path, Manifest())
    writer.commit("a.txt", local_sig="10:1", remote_sig="etag:x", remote_id="id1")
    reloaded = Manifest.from_json(path.read_text())
    assert reloaded.entries["a.txt"].remote_id == "id1"
    # A delete commit (both sigs None) drops the entry and records a tombstone.
    writer.commit("a.txt", local_sig=None, remote_sig=None)
    reloaded2 = Manifest.from_json(path.read_text())
    assert "a.txt" not in reloaded2.entries
    assert "a.txt" in reloaded2.tombstones


def test_sync_lock_is_exclusive(tmp_path) -> None:
    mpath = tmp_path / "pair.manifest.json"
    with SyncLock(mpath), pytest.raises(O2CloudError, match="already running"), SyncLock(mpath):
        pass
    # Lock released on exit — re-acquire succeeds.
    with SyncLock(mpath):
        pass


def test_manifest_path_is_stable_and_pair_specific(tmp_path) -> None:
    a = manifest_path(tmp_path / "x", "/remote", profile="default")
    b = manifest_path(tmp_path / "x", "/other", profile="default")
    assert a != b
    assert a == manifest_path(tmp_path / "x", "/remote", profile="default")
