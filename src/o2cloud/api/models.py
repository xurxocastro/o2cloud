"""Typed pydantic models for SAPI entities.

Field sets mirror the **observed** Funambol OneMediaHub / SAPI response shapes
captured in ``docs/api-reference.md``. Extra fields are tolerated
(``extra="allow"``) so a sparse or slightly-richer real response never crashes
parsing, and ``populate_by_name`` lets a JSON key and a Pythonic alias coexist.

Bytes are integers. Timestamps that SAPI returns as epoch-milliseconds are kept
as raw ``int`` (``*_epoch_ms``) — converting them is a presentation concern and
avoids lossy round-trips.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

_Provisional = ConfigDict(extra="allow", populate_by_name=True)


class _IdCoercingModel(BaseModel):
    """Base that coerces a numeric SAPI ``id`` to ``str`` for uniform handling.

    Folder ids arrive as JSON numbers while media ids arrive as strings; coercing
    to ``str`` lets both flow through the same path/id machinery.
    """

    model_config = _Provisional

    @field_validator("id", mode="before", check_fields=False)
    @classmethod
    def _coerce_id(cls, value: object) -> object:
        if isinstance(value, (int, float)):
            return str(int(value))
        return value


class AuthToken(BaseModel):
    """SAPI session credential descriptor (the secret VALUE is never stored here).

    Only non-secret metadata belongs in persisted models; the ``validationKey``
    string itself lives in the keyring. Used transiently in memory during login.
    """

    model_config = _Provisional

    token_type: str = "validationKey"
    expires_at: datetime | None = None
    account_id: str | None = None


class Individual(BaseModel):
    """Per-user slice of the storage-space envelope (``data.individual``)."""

    model_config = _Provisional

    used: int = 0
    softdeleted: int = 0


class Quota(BaseModel):
    """Storage-space usage & limits.

    Shape: ``GET /sapi/media?action=get-storage-space&softdeleted=true`` →
    ``data{quota, free, used, softdeleted, nolimit, individual}`` (bytes).
    """

    model_config = _Provisional

    quota: int = 0  # total capacity in bytes (observed 10 TiB)
    free: int = 0
    used: int = 0
    softdeleted: int = 0
    nolimit: bool = False
    individual: Individual | None = None

    @property
    def total_bytes(self) -> int:
        return self.quota

    @property
    def used_bytes(self) -> int:
        return self.used

    @property
    def free_bytes(self) -> int:
        if self.nolimit:
            return -1  # sentinel: unlimited
        return self.free if self.free else max(self.quota - self.used, 0)


class Account(BaseModel):
    """Account identity / profile (``GET /sapi/profile?action=get`` → ``data``).

    The exact profile field set is not fully pinned in the memo; the common
    Funambol profile keys are declared and everything else is preserved via
    ``extra="allow"``.
    """

    model_config = _Provisional

    account_id: str | None = Field(default=None, alias="userid")
    username: str | None = None
    email: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    msisdn: str | None = None
    active: bool | None = None


class Plan(BaseModel):
    """A subscription plan (``subscription/plan?action=get`` → ``data.plans[]``)."""

    model_config = _Provisional

    name: str | None = None
    price: float | None = None
    currency: str | None = None
    period: str | None = None
    quota: int | str | None = None  # human string ("10T") or byte count, per plan
    nolimit: bool = False


class PlanList(BaseModel):
    """The ``data`` of the subscription-plan endpoint."""

    model_config = _Provisional

    plans: list[Plan] = Field(default_factory=list)


class Folder(_IdCoercingModel):
    """A folder / Funambol auto-folder.

    Shape: ``POST /sapi/media/folder?action=get`` →
    ``data.folders[]{name, id, status, magic, offline, creationdate, date}``.
    ``id`` is a SAPI number; it is coerced to ``str`` for uniform path handling.
    """

    id: str
    name: str
    status: str | None = None
    magic: bool = False  # Funambol auto-folder (Pictures/Videos)
    offline: bool = False
    creationdate: int | str | None = None  # epoch-ms or formatted "YYYYMMDDThhmmssZ"
    date: int | None = None  # epoch-ms
    parent_id: str | None = Field(default=None, validation_alias=AliasChoices("parent_id", "parentid"))
    path: str | None = None

    @field_validator("parent_id", mode="before", check_fields=False)
    @classmethod
    def _coerce_parent_id(cls, value: object) -> object:
        if isinstance(value, (int, float)):
            return str(int(value))
        return value


class MediaItem(_IdCoercingModel):
    """A stored media object.

    Listing (``GET /sapi/media?action=get&limit=N``) returns **sparse** items:
    ``{id, date, mediatype, status, userid}``. The richer per-item metadata
    (``name``/``size``/``contenttype``) comes from a per-type detail call and is
    optional here so a sparse listing parses cleanly.
    """

    id: str
    date: int | None = None  # epoch-ms
    mediatype: Literal["file", "picture", "video", "audio"] | str | None = None
    status: str | None = None  # "U" = uploaded/valid
    userid: str | None = None
    # Detail fields (populated by POST /sapi/media/file?action=get {data:{files:[{id}]}}).
    name: str | None = None
    size: int | None = None
    contenttype: str | None = None
    folder_id: str | None = None
    url: str | None = None  # direct download link (append ?validationkey=)
    path: str | None = None
    etag: str | None = None  # remote validator for resumable download


class MediaListing(BaseModel):
    """``data`` of a media listing: ``{media[], more(bool)}`` (``more`` = paginate)."""

    model_config = _Provisional

    media: list[MediaItem] = Field(default_factory=list)
    more: bool = False


class FileItem(MediaItem):
    """Discriminated ``file`` variant of a remote item."""

    kind: Literal["file"] = "file"


class FolderItem(Folder):
    """Discriminated ``folder`` variant of a remote item."""

    kind: Literal["folder"] = "folder"


RemoteItem = Annotated[FileItem | FolderItem, Field(discriminator="kind")]
"""A remote entry, discriminated on ``kind`` (``file`` | ``folder``)."""


class UploadResult(_IdCoercingModel):
    """Response of the upload action: ``{success, id, etag, status, type}``.

    ``id`` = new item id; ``etag`` = integrity/resume validator.
    """

    success: bool | str = False
    id: str = ""
    etag: str | None = None
    status: str | None = None
    type: str | None = None


class ValidationEntry(_IdCoercingModel):
    """One ``{id, status}`` from ``action=get-validation-status``."""

    id: str
    status: str | None = None


class ShareLink(BaseModel):
    """A share link / media-set link (best-effort; may be a documented gap)."""

    model_config = _Provisional

    id: str
    item_id: str | None = None
    url: str | None = None
    expires_at: datetime | None = None


class TrashItem(BaseModel):
    """A soft-deleted (trashed) media item."""

    model_config = _Provisional

    id: str
    name: str | None = None
    mediatype: str | None = None
    original_path: str | None = None
    deleted_at: datetime | None = None


class UploadSession(BaseModel):
    """Resumable-upload session state (committed-offset).

    ``committed_offset`` is the server-reported byte offset already persisted, so a
    retried chunk resumes rather than duplicating.
    """

    model_config = _Provisional

    upload_id: str
    committed_offset: int = 0
    total_size: int = 0


class SyncAction(BaseModel):
    """One planned action in a sync run."""

    model_config = _Provisional

    op: Literal[
        "upload",
        "download",
        "delete_local",
        "delete_remote",
        "conflict",
        "noop",
    ]
    path: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"op": self.op, "path": self.path}
        if self.reason:
            payload["reason"] = self.reason
        return payload


class SyncPlan(BaseModel):
    """The full set of actions a sync run would take (``--dry-run`` prints this)."""

    model_config = _Provisional

    actions: list[SyncAction] = Field(default_factory=list)

    @property
    def conflicts(self) -> list[SyncAction]:
        return [a for a in self.actions if a.op == "conflict"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [a.to_dict() for a in self.actions],
            "conflicts": len(self.conflicts),
        }


__all__ = [
    "AuthToken",
    "Individual",
    "Quota",
    "Account",
    "Plan",
    "PlanList",
    "Folder",
    "MediaItem",
    "MediaListing",
    "FileItem",
    "FolderItem",
    "RemoteItem",
    "UploadResult",
    "ValidationEntry",
    "ShareLink",
    "TrashItem",
    "UploadSession",
    "SyncAction",
    "SyncPlan",
]
