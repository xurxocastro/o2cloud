"""SAPI resource parsing/choreography against the captured JSON shapes (respx)."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from o2cloud.api.client import SapiClient
from o2cloud.api.folders import FoldersApi
from o2cloud.api.media import MediaApi
from o2cloud.api.quota import QuotaApi
from o2cloud.config import AppConfig
from o2cloud.secrets import SecretStore

TOKEN = "0123456789abcdef0123456789abcdef"  # placeholder validationKey (not real)
SAPI = "https://cloud.o2online.es/sapi"
UPLOAD = "https://upload.cloud.o2online.es/sapi/upload"


def _client() -> SapiClient:
    store = SecretStore("default")
    store.set("token", TOKEN)
    return SapiClient(AppConfig(), store)


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"data": data, "responsetime": 1})


@respx.mock
def test_quota_parsing_from_storage_space_shape() -> None:
    respx.get(f"{SAPI}/media").mock(
        return_value=_ok(
            {
                "quota": 10995116277760,
                "free": 10995116277000,
                "used": 760,
                "softdeleted": 0,
                "nolimit": False,
                "individual": {"used": 760, "softdeleted": 0},
            }
        )
    )
    with _client() as client:
        quota = QuotaApi(client).get_quota()
    assert quota.total_bytes == 10995116277760
    assert quota.used_bytes == 760
    assert quota.individual is not None
    assert quota.individual.used == 760


@respx.mock
def test_account_parsing_userid_alias() -> None:
    respx.get(f"{SAPI}/profile").mock(
        return_value=_ok({"userid": "user-123", "username": "someone", "email": "a@b.c"})
    )
    with _client() as client:
        account = QuotaApi(client).get_account()
    assert account.account_id == "user-123"
    assert account.username == "someone"


@respx.mock
def test_plan_parsing() -> None:
    respx.get(f"{SAPI}/subscription/plan").mock(
        return_value=_ok(
            {"plans": [{"name": "Free 10TB", "quota": 10995116277760, "nolimit": False}]}
        )
    )
    with _client() as client:
        plans = QuotaApi(client).get_plan()
    assert len(plans) == 1
    assert plans[0].name == "Free 10TB"


@respx.mock
def test_folder_listing_parsing() -> None:
    respx.post(f"{SAPI}/media/folder").mock(
        return_value=_ok(
            {
                "folders": [
                    {
                        "name": "Pictures",
                        "id": 1001,
                        "status": "N",
                        "magic": True,
                        "offline": False,
                        "creationdate": 1600000000000,
                        "date": 1600000000000,
                    }
                ]
            }
        )
    )
    with _client() as client:
        folders = list(FoldersApi(client).list())
    assert folders[0].name == "Pictures"
    assert folders[0].id == "1001"  # numeric id coerced to str
    assert folders[0].magic is True


@respx.mock
def test_folder_create() -> None:
    route = respx.post(f"{SAPI}/media/folder").mock(return_value=_ok({"id": 2002, "name": "New"}))
    with _client() as client:
        folder = FoldersApi(client).create("New")
    assert folder.id == "2002"
    assert route.calls.last.request.url.params["action"] == "save"


@respx.mock
def test_media_listing_is_sparse_and_paginates() -> None:
    respx.get(f"{SAPI}/media").mock(
        return_value=_ok(
            {
                "media": [
                    {
                        "id": "m1",
                        "date": 1600000000000,
                        "mediatype": "file",
                        "status": "U",
                        "userid": "u1",
                    },
                    {
                        "id": "m2",
                        "date": 1600000000001,
                        "mediatype": "picture",
                        "status": "U",
                        "userid": "u1",
                    },
                ],
                "more": True,
            }
        )
    )
    with _client() as client:
        listing = MediaApi(client).list(limit=2)
    assert listing.more is True
    assert [m.id for m in listing.media] == ["m1", "m2"]
    assert listing.media[0].name is None  # sparse: no name until detail


@respx.mock
def test_upload_choreography_saves_then_validates(tmp_path: Path) -> None:
    src = tmp_path / "hello.txt"
    src.write_text("hi")

    save = respx.post(UPLOAD).mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "id": "new-1", "etag": "etag-1", "status": "U", "type": "file"},
        )
    )
    validate = respx.post(f"{SAPI}/media").mock(
        return_value=_ok({"ids": [{"id": "new-1", "status": "U"}]})
    )
    with _client() as client:
        result = MediaApi(client).upload(src)
    assert result.id == "new-1"
    assert result.etag == "etag-1"
    assert save.called
    assert validate.called
    # X-deviceid header is present on the upload request.
    assert "x-deviceid" in {k.lower() for k in save.calls.last.request.headers}


@respx.mock
def test_delete_soft_by_default_and_permanent() -> None:
    route = respx.post(f"{SAPI}/media/file").mock(return_value=_ok({"success": True}))
    with _client() as client:
        MediaApi(client).delete("m1")
        assert route.calls.last.request.url.params["action"] == "softdelete"
        MediaApi(client).delete("m1", permanent=True)
        assert route.calls.last.request.url.params["action"] == "delete"


@respx.mock
def test_validation_status_parsing() -> None:
    respx.post(f"{SAPI}/media").mock(
        return_value=_ok({"ids": [{"id": "m1", "status": "U"}, {"id": "m2", "status": "P"}]})
    )
    with _client() as client:
        entries = list(MediaApi(client).validation_status(["m1", "m2"]))
    assert entries[0].id == "m1"
    assert entries[1].status == "P"


@respx.mock
def test_search_is_client_side_filter() -> None:
    respx.get(f"{SAPI}/media").mock(
        return_value=_ok(
            {
                "media": [
                    {"id": "m1", "name": "report.pdf", "mediatype": "file"},
                    {"id": "m2", "name": "photo.jpg", "mediatype": "picture"},
                ],
                "more": False,
            }
        )
    )
    with _client() as client:
        hits = list(MediaApi(client).search("report"))
    assert [h.id for h in hits] == ["m1"]
