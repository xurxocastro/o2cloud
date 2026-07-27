"""Service-layer orchestration: listing, conflict-aware upload, resolution (respx)."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from o2cloud.config import AppConfig
from o2cloud.errors import NotFoundError
from o2cloud.secrets import SecretStore
from o2cloud.service import ConflictPolicy, O2CloudService

TOKEN = "0123456789abcdef0123456789abcdef"  # placeholder validationKey (not real)
SAPI = "https://cloud.o2online.es/sapi"
UPLOAD = "https://upload.cloud.o2online.es/sapi/upload"


def _service() -> O2CloudService:
    store = SecretStore("default")
    store.set("token", TOKEN)
    return O2CloudService(AppConfig(), store)


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "responsetime": 1})


@respx.mock
def test_list_dir_combines_folders_and_media() -> None:
    respx.post(f"{SAPI}/media/folder").mock(
        return_value=_ok({"folders": [{"id": 1, "name": "Pictures"}]})
    )
    respx.get(f"{SAPI}/media").mock(
        return_value=_ok({"media": [{"id": "m1", "mediatype": "file"}], "more": False})
    )
    svc = _service()
    entries = svc.list_dir("/", detail=False)  # raw combine; enrichment tested separately
    svc.close()
    kinds = {e.name or e.id: e.mediatype for e in entries}
    assert kinds["Pictures"] == "folder"
    assert kinds["m1"] == "file"


@respx.mock
def test_list_dir_enriches_file_names(tmp_path: Path) -> None:
    """detail=True (default) resolves sparse file ids into names via batch detail."""
    respx.post(f"{SAPI}/media/folder").mock(return_value=_ok({"folders": []}))
    respx.get(f"{SAPI}/media").mock(
        return_value=_ok({"media": [{"id": "m1", "mediatype": "file"}], "more": False})
    )
    respx.post(f"{SAPI}/media/file").mock(
        return_value=_ok(
            {"files": [{"id": "m1", "name": "note.txt", "size": 5, "mediatype": "file"}]}
        )
    )
    svc = _service()
    entries = svc.list_dir("/")  # detail defaults to True
    svc.close()
    files = [e for e in entries if e.mediatype == "file"]
    assert files[0].name == "note.txt"  # sparse id resolved to a name
    assert files[0].size == 5


@respx.mock
def test_list_dir_enrichment_falls_back_on_error() -> None:
    """A failing batch detail leaves files sparse — the listing still succeeds."""
    respx.post(f"{SAPI}/media/folder").mock(return_value=_ok({"folders": []}))
    respx.get(f"{SAPI}/media").mock(
        return_value=_ok({"media": [{"id": "m1", "mediatype": "file"}], "more": False})
    )
    respx.post(f"{SAPI}/media/file").mock(
        return_value=httpx.Response(
            200, json={"error": {"code": "MED-9999", "message": "boom"}, "responsetime": 1}
        )
    )
    svc = _service()
    entries = svc.list_dir("/")
    svc.close()
    files = [e for e in entries if e.mediatype == "file"]
    assert files[0].id == "m1"  # still listed, just without a name
    assert files[0].name is None


@respx.mock
def test_upload_conflict_when_destination_exists() -> None:
    # Destination folder is root (no folder call); the media listing shows an
    # existing item named like the upload source → conflict under the default.
    respx.get(f"{SAPI}/media").mock(
        return_value=_ok({"media": [{"id": "x", "name": "hello.txt"}], "more": False})
    )
    # Source basename must collide with the existing remote item name.
    src = Path(__file__).parent / "hello.txt"
    src.write_text("hi")
    try:
        svc = _service()
        items = svc.upload([src], "/", policy=ConflictPolicy.FAIL)
        svc.close()
    finally:
        src.unlink()
    assert len(items) == 1
    assert items[0].status == "conflict"


@respx.mock
def test_upload_skip_when_destination_exists() -> None:
    respx.get(f"{SAPI}/media").mock(
        return_value=_ok({"media": [{"id": "x", "name": "hello.txt"}], "more": False})
    )
    collide = Path(__file__).parent / "hello.txt"
    collide.write_text("hi")
    try:
        svc = _service()
        items = svc.upload([collide], "/", policy=ConflictPolicy.SKIP)
        svc.close()
    finally:
        collide.unlink()
    assert items[0].status == "skipped"


@respx.mock
def test_upload_success_when_no_conflict(tmp_path: Path) -> None:
    respx.get(f"{SAPI}/media").mock(return_value=_ok({"media": [], "more": False}))
    respx.post(UPLOAD).mock(
        return_value=httpx.Response(200, json={"success": True, "id": "new-1", "etag": "e1"})
    )
    respx.post(f"{SAPI}/media").mock(return_value=_ok({"ids": [{"id": "new-1", "status": "U"}]}))
    src = tmp_path / "fresh.txt"
    src.write_text("data")
    svc = _service()
    items = svc.upload([src], "/", policy=ConflictPolicy.FAIL)
    svc.close()
    assert items[0].status == "ok"
    assert items[0].detail is not None
    assert items[0].detail["id"] == "new-1"


@respx.mock
def test_download_uses_detail_url(tmp_path: Path) -> None:
    # 1) listing (sparse) so resolve_item locates the item by name.
    respx.get(f"{SAPI}/media").mock(
        return_value=_ok(
            {"media": [{"id": "d1", "name": "note.txt", "mediatype": "file"}], "more": False}
        )
    )
    # 2) detail POST /sapi/media/file?action=get → full item incl. url.
    respx.post(f"{SAPI}/media/file").mock(
        return_value=_ok(
            {
                "files": [
                    {
                        "id": "d1",
                        "name": "note.txt",
                        "size": 5,
                        "etag": "e9",
                        "mediatype": "file",
                        "url": "https://cloud.o2online.es/download/d1",
                    }
                ]
            }
        )
    )
    # 3) the item url returns the bytes (validationkey is appended by the client).
    respx.get(url__regex=r"https://cloud\.o2online\.es/download/d1.*").mock(
        return_value=httpx.Response(200, content=b"hello", headers={"content-type": "text/plain"})
    )
    svc = _service()
    items = svc.download(["note.txt"], tmp_path, policy=ConflictPolicy.FAIL)
    svc.close()
    assert items[0].status == "ok"
    assert (tmp_path / "note.txt").read_bytes() == b"hello"


@respx.mock
def test_resolve_folder_walks_named_path() -> None:
    # /Pictures resolves against the root folder listing.
    respx.post(f"{SAPI}/media/folder").mock(
        return_value=_ok({"folders": [{"id": 7, "name": "Pictures"}]})
    )
    svc = _service()
    folder_id = svc.resolver.resolve_folder("/Pictures")
    svc.close()
    assert folder_id == "7"


@respx.mock
def test_resolve_folder_missing_raises_not_found() -> None:
    respx.post(f"{SAPI}/media/folder").mock(return_value=_ok({"folders": []}))
    svc = _service()
    try:
        svc.resolver.resolve_folder("/Nope")
    except NotFoundError as exc:
        assert exc.detail["missing"] == "Nope"
    else:  # pragma: no cover
        raise AssertionError("expected NotFoundError")
    finally:
        svc.close()


@respx.mock
def test_download_rejects_path_traversal_name(tmp_path: Path) -> None:
    """M1 regression: a server-supplied ../ name is confined to a basename in dest."""
    respx.get(f"{SAPI}/media").mock(
        return_value=_ok(
            {"media": [{"id": "d1", "name": "note.txt", "mediatype": "file"}], "more": False}
        )
    )
    respx.post(f"{SAPI}/media/file").mock(
        return_value=_ok(
            {
                "files": [
                    {
                        "id": "d1",
                        "name": "../../evil.txt",
                        "size": 3,
                        "mediatype": "file",
                        "url": "https://cloud.o2online.es/download/d1",
                    }
                ]
            }
        )
    )
    respx.get(url__regex=r"https://cloud\.o2online\.es/download/d1.*").mock(
        return_value=httpx.Response(200, content=b"xxx")
    )
    outdir = tmp_path / "dl"
    outdir.mkdir()
    svc = _service()
    items = svc.download(["note.txt"], outdir, policy=ConflictPolicy.FAIL)
    svc.close()
    assert items[0].status == "ok"
    assert (outdir / "evil.txt").read_bytes() == b"xxx"  # basename, inside dest
    assert not (tmp_path / "evil.txt").exists()  # did NOT escape one level up
