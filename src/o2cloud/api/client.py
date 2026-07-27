"""SAPI HTTP transport wrapper.

Wraps an ``httpx.Client`` for the Funambol OneMediaHub SAPI. On **every**
``/sapi/*`` call the token (the Funambol ``validationKey``, 32 hex) is sent as
**both** the ``validationKey`` cookie **and** the ``?validationkey=`` query param
(memo § Token mechanism). Responses use the SAPI envelope — success
``{data, responsetime}`` / error ``{error{code,message,parameters,cause},
responsetime}`` — and an error body may arrive with HTTP 200, so the client
branches on ``data`` vs ``error`` rather than on status alone.

Retry policy (plan § api/client): automatic ``tenacity`` retry/backoff applies
**only to idempotent** requests (GET/HEAD). Non-idempotent mutations are never
blindly retried here; the service layer reconciles state before any replay.

Error mapping: transport failures → :class:`NetworkError`; HTTP 401/403 →
:class:`AuthError`; HTTP 429 → :class:`RateLimitedError`; a SAPI error envelope
is mapped by code/prefix to the typed taxonomy (unmapped → :class:`ServerError`,
carrying the raw SAPI code in ``detail``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx
from tenacity import (
    Retrying as _Retrying,
)
from tenacity import (
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import AppConfig
from ..errors import (
    AuthError,
    NetworkError,
    NotFoundError,
    O2CloudError,
    QuotaError,
    RateLimitedError,
    ServerError,
)
from ..logging import get_logger
from ..secrets import SecretStore

_log = get_logger()

# Upload multipart part names — CONFIRMED live 2026-07-22 against the real
# upload host: a "data" part carrying the JSON metadata (wrapped as
# {"data": {name, size, modificationdate, …}}) and a "file" part with the bytes.
UPLOAD_PART_FILE = "file"
UPLOAD_PART_METADATA = "data"

# SAPI error-code → typed exception. Only the observed/likely codes are pinned;
# everything else falls through to a prefix rule then :class:`ServerError`.
_SAPI_CODE_MAP: dict[str, type[O2CloudError]] = {
    "MED-1000": NotFoundError,  # media not found / bad media request (memo)
    "MED-1001": NotFoundError,
}

# SAPI resource-prefix → typed exception (Funambol namespaces its codes by
# resource, e.g. ``SEC-*`` security, ``PRO-*`` profile, ``COM-*`` common).
_SAPI_PREFIX_MAP: dict[str, type[O2CloudError]] = {
    "SEC": AuthError,  # security / authorization
    "AUT": AuthError,
    "QUO": QuotaError,  # quota-related codes, if the backend emits them
}


def _map_sapi_error(
    code: str,
    message: str,
    *,
    parameters: Any = None,
    cause: Any = None,
) -> O2CloudError:
    """Map a SAPI error envelope to a typed :class:`O2CloudError`."""
    detail: dict[str, Any] = {"sapi_code": code}
    if cause:
        detail["sapi_cause"] = cause
    if parameters:
        detail["sapi_parameters"] = parameters

    exc_type: type[O2CloudError] | None = _SAPI_CODE_MAP.get(code)
    if exc_type is None and code:
        prefix = code.split("-", 1)[0].upper()
        exc_type = _SAPI_PREFIX_MAP.get(prefix)
    if exc_type is None:
        exc_type = ServerError
    return exc_type(message or f"SAPI error {code}", detail=detail)


class SapiClient:
    """Thin, injectable SAPI transport.

    The service layer receives an instance so the CLI stays thin and everything is
    unit-testable against ``respx``-mocked HTTP. Two ``httpx.Client``s are held:
    the SAPI client (``<base_url>/sapi``) and the dedicated upload-host client
    (``<upload_base_url>/sapi/upload``).
    """

    def __init__(
        self,
        config: AppConfig,
        secret_store: SecretStore,
        *,
        transport: httpx.BaseTransport | None = None,
        upload_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self.secrets = secret_store
        self._sapi_base = config.base_url.rstrip("/") + "/sapi"
        self._upload_url = config.upload_base_url.rstrip("/") + "/sapi/upload"
        # HTTP/2 is intentionally OFF: the ``h2`` extra is not a hard dependency,
        # and SAPI is served fine over HTTP/1.1. Flip on once ``httpx[http2]`` is
        # pinned if connection multiplexing becomes worthwhile.
        self._client = httpx.Client(
            base_url=self._sapi_base,
            headers=self._default_headers(),
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=transport,
        )
        self._upload_client = httpx.Client(
            headers=self._default_headers(),
            timeout=httpx.Timeout(300.0, connect=10.0),
            transport=upload_transport,
        )

    # --- headers / auth ---------------------------------------------------
    def _default_headers(self) -> dict[str, str]:
        return {"User-Agent": self.config.user_agent, "Accept": "application/json"}

    def validation_key(self) -> str:
        """Return the stored ``validationKey`` or raise :class:`AuthError`.

        The token is the sole auth credential; its absence is an auth failure so
        every endpoint returns the auth envelope + exit 2 when not logged in.
        """
        token = self.secrets.token
        if not token:
            raise AuthError(
                "not authenticated — run 'o2cloud login' or set O2CLOUD_TOKEN",
                detail={"hint": "validationKey missing"},
            )
        return token

    def _auth_params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(params or {})
        merged["validationkey"] = self.validation_key()
        return merged

    def _session_cookies(self) -> dict[str, str]:
        """Parse the stored Cookie header into name=value pairs.

        O2's SAPI needs the ``JSESSIONID`` session cookie (httpOnly) in addition
        to ``validationKey``; the token alone returns 401. The full cookie header
        captured at login is replayed here. Falls back to just ``validationKey``.
        """
        raw = self.secrets.cookie
        pairs: dict[str, str] = {}
        if raw:
            for part in raw.split(";"):
                part = part.strip()
                if "=" in part:
                    name, value = part.split("=", 1)
                    if name.strip():
                        pairs[name.strip()] = value.strip()
        pairs.setdefault("validationKey", self.validation_key())
        return pairs

    def _apply_session_cookies(self, client: httpx.Client) -> None:
        """Set the stored session cookies on *client*'s jar (not per-request)."""
        for name, value in self._session_cookies().items():
            client.cookies.set(name, value)

    # --- envelope handling ------------------------------------------------
    @staticmethod
    def _parse_envelope(response: httpx.Response) -> dict[str, Any]:
        """Return the ``data`` object, raising a typed error for an error body.

        Branches on ``data`` vs ``error`` (SAPI may return an error with HTTP
        200). HTTP transport statuses are mapped first so a 401/403/429 is typed
        even when the body is not the usual envelope.
        """
        status = response.status_code
        if status in (401, 403):
            raise AuthError(
                "SAPI rejected the session (re-authenticate with 'o2cloud login')",
                detail={"http_status": status},
            )
        if status == 429:
            raise RateLimitedError(
                "rate limited by SAPI (HTTP 429)", detail={"http_status": status}
            )

        try:
            payload: Any = response.json()
        except ValueError:
            # Non-JSON (e.g. an SPA HTML shell) — treat 5xx as transient network,
            # everything else as an opaque server error.
            if status >= 500:
                raise NetworkError(
                    f"SAPI returned a non-JSON {status} response",
                    detail={"http_status": status},
                ) from None
            raise ServerError(
                "SAPI returned a non-JSON response",
                detail={"http_status": status},
            ) from None

        if isinstance(payload, dict) and "error" in payload and payload["error"]:
            err = payload["error"]
            raise _map_sapi_error(
                str(err.get("code", "")),
                str(err.get("message", "")),
                parameters=err.get("parameters"),
                cause=err.get("cause"),
            )

        if status >= 500:
            raise NetworkError(f"SAPI server error (HTTP {status})", detail={"http_status": status})
        if isinstance(payload, dict) and "data" in payload:
            data = payload["data"]
            return data if isinstance(data, dict) else {"value": data}
        # A bare object without the envelope (some actions return the object
        # directly, e.g. the upload host); hand it back verbatim.
        return payload if isinstance(payload, dict) else {"value": payload}

    # --- core request -----------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        idempotent: bool | None = None,
    ) -> dict[str, Any]:
        """Perform a SAPI request and return the parsed ``data`` object.

        ``idempotent`` defaults to ``True`` for GET/HEAD (which are retried on a
        transient transport/5xx failure) and ``False`` otherwise (no blind
        replay). The ``validationkey`` query param and ``validationKey`` cookie
        are attached automatically.
        """
        if idempotent is None:
            idempotent = method.upper() in ("GET", "HEAD")

        def _do() -> dict[str, Any]:
            # Replay the full session cookie jar (JSESSIONID + validationKey + …);
            # set on the client (not per-request, which httpx deprecates).
            self._apply_session_cookies(self._client)
            try:
                response = self._client.request(
                    method,
                    path,
                    params=self._auth_params(params),
                    json=json_body,
                )
            except httpx.TransportError as exc:
                raise NetworkError(
                    f"transport error talking to SAPI: {exc}",
                    detail={"path": path},
                ) from exc
            return self._parse_envelope(response)

        if not idempotent:
            return _do()

        retryer = _Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, max=4.0),
            retry=retry_if_exception_type((NetworkError, RateLimitedError)),
            reraise=True,
        )
        return retryer(_do)

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", path, params=params)

    def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        return self.request("POST", path, params=params, json_body=json_body, idempotent=idempotent)

    # --- upload host ------------------------------------------------------
    def upload_save(
        self,
        source: Path,
        *,
        remote_name: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST a file to the dedicated upload host (``action=save``).

        Multipart ``FormData`` (CONFIRMED live 2026-07-22): a ``data`` part with
        JSON ``{"data": {name, size, modificationdate, …}}`` and a ``file`` part
        with the bytes, ``X-deviceid`` header. Returns the parsed response object
        ``{success, id, etag, status, type}``.
        """
        name = remote_name or source.name
        stat = source.stat()
        size = stat.st_size
        # SAPI expects the compact UTC form "YYYYMMDDThhmmssZ" (confirmed live:
        # epoch-ms is rejected with COM-1008 on modificationdate/creationdate).
        ts = datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        headers = {
            "X-deviceid": self.config.device_id or "o2cloud-cli",
            "x-funambol-file-size": str(size),
        }
        # Metadata JSON is wrapped in a "data" key (confirmed from real traffic).
        inner: dict[str, Any] = {
            "name": name,
            "size": size,
            "modificationdate": ts,
            "creationdate": ts,
        }
        if extra_metadata:
            inner.update(extra_metadata)

        self._apply_session_cookies(self._upload_client)
        try:
            with source.open("rb") as fh:
                files = {UPLOAD_PART_FILE: (name, fh, "application/octet-stream")}
                data = {UPLOAD_PART_METADATA: _json_dumps({"data": inner})}
                response = self._upload_client.post(
                    self._upload_url,
                    params={"action": "save", "validationkey": self.validation_key()},
                    files=files,
                    data=data,
                    headers=headers,
                )
        except httpx.TransportError as exc:
            raise NetworkError(
                f"transport error during upload: {exc}", detail={"name": name}
            ) from exc
        return self._parse_envelope(response)

    # --- content download -------------------------------------------------
    def get_bytes(self, url: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
        """GET a URL and return the raw response (no envelope parsing)."""
        try:
            return self._client.get(url, headers=headers, follow_redirects=True)
        except httpx.TransportError as exc:
            # Strip the query — the token lives there — before surfacing the URL.
            safe = str(httpx.URL(url).copy_with(query=None))
            raise NetworkError(
                f"transport error downloading content: {exc}", detail={"url": safe}
            ) from exc

    def download_url(self, url: str) -> httpx.Response:
        """Download a media item's ``url`` field (the direct download link).

        Confirmed live: the media-detail ``url`` is a **host-relative signed path**
        like ``/sapi/download/file?action=get&k=<signature>&node=<n>``. The ``k``
        token self-authenticates the request. It MUST be made absolute against the
        SAPI origin — passing the relative ``/sapi/...`` path to the base-url client
        makes httpx concatenate the base path (``/sapi``) and hit
        ``/sapi/sapi/...``, which the server answers with the SPA shell (HTML).
        """
        if url.startswith("/"):
            url = self.config.base_url.rstrip("/") + url
        self._apply_session_cookies(self._client)
        return self.get_bytes(url)

    # --- lifecycle --------------------------------------------------------
    def close(self) -> None:
        self._client.close()
        self._upload_client.close()

    def __enter__(self) -> SapiClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


__all__ = ["SapiClient", "UPLOAD_PART_FILE", "UPLOAD_PART_METADATA"]
