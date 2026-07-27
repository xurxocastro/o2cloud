"""Output contract: envelopes, batch aggregation precedence, exit codes, streams."""

from __future__ import annotations

import io
import json

import pytest

from o2cloud import output
from o2cloud.errors import (
    ConflictError,
    NetworkError,
    NotFoundError,
    QuotaError,
    UsageError,
)
from o2cloud.output import BatchItem


# --- single envelopes -------------------------------------------------------
def test_success_envelope_shape() -> None:
    assert output.success_envelope("ls", [1, 2]) == {
        "ok": True,
        "command": "ls",
        "data": [1, 2],
    }


def test_error_envelope_shape() -> None:
    env = output.error_envelope("stat", NotFoundError("nope", detail={"path": "/x"}))
    assert env == {
        "ok": False,
        "command": "stat",
        "error": {"code": "not_found", "message": "nope", "detail": {"path": "/x"}},
    }


# --- BatchItem construction -------------------------------------------------
def test_batch_item_constructors_and_serialization() -> None:
    ok = BatchItem.ok("/a", size=10)
    skip = BatchItem.skipped("/b", message="exists")
    conflict = BatchItem.conflict("/c")
    failed = BatchItem.failed("/d", NotFoundError("gone"))

    assert ok.status == "ok" and ok.to_dict()["detail"] == {"size": 10}
    assert skip.to_dict() == {"target": "/b", "status": "skipped", "message": "exists"}
    assert conflict.to_dict() == {"target": "/c", "status": "conflict"}
    d = failed.to_dict()
    assert d["status"] == "failed" and d["code"] == "not_found" and d["message"] == "gone"


def test_item_exit_code_per_status() -> None:
    assert BatchItem.ok("/a").item_exit_code() == 0
    assert BatchItem.skipped("/a").item_exit_code() == 0
    assert BatchItem.conflict("/a").item_exit_code() == 4
    assert BatchItem.failed("/a", QuotaError("x")).item_exit_code() == 7


# --- aggregate exit code: every branch --------------------------------------
def test_aggregate_empty_is_zero() -> None:
    assert output.aggregate_exit_code([]) == 0


def test_aggregate_single_item_uses_item_code() -> None:
    assert output.aggregate_exit_code([BatchItem.failed("/a", NetworkError("x"))]) == 5
    assert output.aggregate_exit_code([BatchItem.conflict("/a")]) == 4
    assert output.aggregate_exit_code([BatchItem.ok("/a")]) == 0


def test_aggregate_all_ok() -> None:
    items = [BatchItem.ok("/a"), BatchItem.ok("/b")]
    assert output.aggregate_exit_code(items) == 0


def test_aggregate_all_skipped() -> None:
    items = [BatchItem.skipped("/a"), BatchItem.skipped("/b")]
    assert output.aggregate_exit_code(items) == 0


def test_aggregate_ok_plus_skipped_is_zero() -> None:
    items = [BatchItem.ok("/a"), BatchItem.skipped("/b")]
    assert output.aggregate_exit_code(items) == 0


def test_aggregate_all_conflict() -> None:
    items = [BatchItem.conflict("/a"), BatchItem.conflict("/b")]
    assert output.aggregate_exit_code(items) == 4


def test_aggregate_all_failed_single_cause_uses_that_code() -> None:
    items = [
        BatchItem.failed("/a", NotFoundError("x")),
        BatchItem.failed("/b", NotFoundError("y")),
    ]
    assert output.aggregate_exit_code(items) == 3


def test_aggregate_all_failed_multiple_causes_is_partial_batch() -> None:
    items = [
        BatchItem.failed("/a", NotFoundError("x")),
        BatchItem.failed("/b", QuotaError("y")),
    ]
    assert output.aggregate_exit_code(items) == 8


def test_aggregate_mixed_with_failed_is_partial_batch() -> None:
    items = [BatchItem.ok("/a"), BatchItem.failed("/b", NotFoundError("x"))]
    assert output.aggregate_exit_code(items) == 8


def test_aggregate_conflict_and_failed_is_partial_batch() -> None:
    items = [BatchItem.conflict("/a"), BatchItem.failed("/b", NotFoundError("x"))]
    assert output.aggregate_exit_code(items) == 8


def test_aggregate_mixed_conflict_no_failed_is_conflict() -> None:
    items = [BatchItem.ok("/a"), BatchItem.conflict("/b")]
    assert output.aggregate_exit_code(items) == 4


def test_aggregate_skipped_plus_conflict_is_conflict() -> None:
    items = [BatchItem.skipped("/a"), BatchItem.conflict("/b")]
    assert output.aggregate_exit_code(items) == 4


# --- batch envelope + ok flag + aggregate error -----------------------------
def test_batch_envelope_all_ok_is_true_no_error() -> None:
    env, code = output.batch_envelope("upload", [BatchItem.ok("/a"), BatchItem.skipped("/b")])
    assert env["ok"] is True
    assert "error" not in env
    assert code == 0
    assert [d["status"] for d in env["data"]] == ["ok", "skipped"]


def test_batch_envelope_conflict_has_aggregate_error_and_counts() -> None:
    env, code = output.batch_envelope("upload", [BatchItem.ok("/a"), BatchItem.conflict("/b")])
    assert env["ok"] is False
    assert code == 4
    assert env["error"]["code"] == "conflict"
    assert env["error"]["counts"] == {"ok": 1, "conflict": 1}


def test_batch_envelope_homogeneous_failure_reports_common_cause() -> None:
    env, code = output.batch_envelope(
        "download",
        [BatchItem.failed("/a", NotFoundError("x")), BatchItem.failed("/b", NotFoundError("y"))],
    )
    assert code == 3
    assert env["error"]["code"] == "not_found"
    assert env["error"]["counts"] == {"failed": 2}


def test_batch_envelope_mixed_failure_is_partial_failure() -> None:
    env, code = output.batch_envelope(
        "download",
        [BatchItem.failed("/a", NotFoundError("x")), BatchItem.failed("/b", QuotaError("y"))],
    )
    assert code == 8
    assert env["error"]["code"] == "partial_failure"


def test_batch_data_always_present_even_on_failure() -> None:
    env, _ = output.batch_envelope("rm", [BatchItem.failed("/a", UsageError("x"))])
    assert "data" in env and len(env["data"]) == 1


# --- emission (stream rule) -------------------------------------------------
def test_emit_success_json_writes_envelope_to_out() -> None:
    buf = io.StringIO()
    code = output.emit_success("ls", {"x": 1}, json_mode=True, out=buf)
    assert code == 0
    assert json.loads(buf.getvalue()) == {"ok": True, "command": "ls", "data": {"x": 1}}


def test_emit_success_human_writes_plain_text() -> None:
    buf = io.StringIO()
    output.emit_success("ls", "hello", json_mode=False, out=buf, human="hello")
    assert buf.getvalue().strip() == "hello"


def test_emit_error_returns_exit_code_and_writes_json() -> None:
    buf = io.StringIO()
    code = output.emit_error("stat", ConflictError("dup"), json_mode=True, out=buf)
    assert code == 4
    parsed = json.loads(buf.getvalue())
    assert parsed["ok"] is False and parsed["error"]["code"] == "conflict"


def test_emit_batch_returns_aggregate_code() -> None:
    buf = io.StringIO()
    items = [BatchItem.ok("/a"), BatchItem.failed("/b", NotFoundError("x"))]
    code = output.emit_batch("upload", items, json_mode=True, out=buf)
    assert code == 8
    assert json.loads(buf.getvalue())["ok"] is False


@pytest.mark.parametrize("json_mode", [True, False])
def test_emit_batch_human_and_json_both_return_same_code(json_mode) -> None:
    buf = io.StringIO()
    items = [BatchItem.conflict("/a"), BatchItem.ok("/b")]
    assert output.emit_batch("mv", items, json_mode=json_mode, out=buf) == 4
