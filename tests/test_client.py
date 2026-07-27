"""SAPI transport: envelope branching, error mapping, auth injection, retry.

All HTTP is mocked with ``respx``; no live network. The token below is a
placeholder 32-hex string, never a real secret.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from o2cloud.api.client import SapiClient
from o2cloud.config import AppConfig
from o2cloud.errors import (
    AuthError,
    NetworkError,
    NotFoundError,
    RateLimitedError,
    ServerError,
)
from o2cloud.secrets import SecretStore

TOKEN = "0123456789abcdef0123456789abcdef"  # placeholder validationKey (not real)
SAPI = "https://cloud.o2online.es/sapi"


def _client(with_token: bool = True) -> SapiClient:
    store = SecretStore("default")
    if with_token:
        store.set("token", TOKEN)
    return SapiClient(AppConfig(), store)


@respx.mock
def test_success_envelope_returns_data() -> None:
    route = respx.get(f"{SAPI}/media").mock(
        return_value=httpx.Response(200, json={"data": {"used": 42}, "responsetime": 1})
    )
    with _client() as client:
        data = client.get("/media", params={"action": "get-storage-space"})
    assert data == {"used": 42}
    assert route.called


@respx.mock
def test_validation_key_sent_as_query_and_cookie() -> None:
    route = respx.get(f"{SAPI}/profile").mock(
        return_value=httpx.Response(200, json={"data": {}, "responsetime": 1})
    )
    with _client() as client:
        client.get("/profile", params={"action": "get"})
    request = route.calls.last.request
    assert request.url.params["validationkey"] == TOKEN
    assert f"validationKey={TOKEN}" in request.headers.get("cookie", "")


@respx.mock
def test_error_envelope_with_http_200_is_branched() -> None:
    respx.get(f"{SAPI}/media").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": {
                    "code": "MED-1000",
                    "message": "bad media",
                    "parameters": [],
                    "cause": "",
                },
                "responsetime": 1,
            },
        )
    )
    with _client() as client, pytest.raises(NotFoundError) as exc:
        client.get("/media", params={"action": "get"})
    assert exc.value.detail["sapi_code"] == "MED-1000"


@respx.mock
def test_unknown_sapi_code_maps_to_server_error() -> None:
    respx.get(f"{SAPI}/x").mock(
        return_value=httpx.Response(
            200, json={"error": {"code": "ZZZ-9", "message": "weird"}, "responsetime": 1}
        )
    )
    with _client() as client, pytest.raises(ServerError) as exc:
        client.get("/x")
    assert exc.value.detail["sapi_code"] == "ZZZ-9"


@respx.mock
def test_security_prefix_maps_to_auth_error() -> None:
    respx.get(f"{SAPI}/x").mock(
        return_value=httpx.Response(
            200, json={"error": {"code": "SEC-1001", "message": "denied"}, "responsetime": 1}
        )
    )
    with _client() as client, pytest.raises(AuthError):
        client.get("/x")


@respx.mock
def test_http_401_maps_to_auth_error() -> None:
    respx.get(f"{SAPI}/x").mock(return_value=httpx.Response(401, text="nope"))
    with _client() as client, pytest.raises(AuthError):
        client.get("/x")


@respx.mock
def test_http_429_maps_to_rate_limited_after_retries() -> None:
    route = respx.get(f"{SAPI}/x").mock(return_value=httpx.Response(429, text="slow"))
    with _client() as client, pytest.raises(RateLimitedError):
        client.get("/x")
    # Idempotent GET is retried: 3 total attempts.
    assert route.call_count == 3


@respx.mock
def test_transport_error_maps_to_network_error() -> None:
    respx.get(f"{SAPI}/x").mock(side_effect=httpx.ConnectError("boom"))
    with _client() as client, pytest.raises(NetworkError):
        client.get("/x")


@respx.mock
def test_non_json_response_maps_to_server_error() -> None:
    respx.get(f"{SAPI}/x").mock(return_value=httpx.Response(200, text="<html>SPA shell</html>"))
    with _client() as client, pytest.raises(ServerError):
        client.get("/x")


def test_missing_token_raises_auth_error_without_network() -> None:
    with _client(with_token=False) as client, pytest.raises(AuthError):
        client.get("/media")


@respx.mock
def test_post_is_not_retried() -> None:
    route = respx.post(f"{SAPI}/media/file").mock(return_value=httpx.Response(429, text="slow"))
    with _client() as client, pytest.raises(RateLimitedError):
        client.post("/media/file", params={"action": "delete"})
    # Non-idempotent POST must not be blindly replayed.
    assert route.call_count == 1
