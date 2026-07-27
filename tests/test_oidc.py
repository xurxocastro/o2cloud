"""OIDC skeleton: authorize-URL construction and redirect parsing (no live calls)."""

from __future__ import annotations

import urllib.parse

import pytest

from o2cloud.auth import oidc
from o2cloud.config import AppConfig
from o2cloud.errors import AuthError, NotImplementedYetError


def _params(url: str) -> dict[str, str]:
    query = urllib.parse.urlparse(url).query
    return {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}


def test_build_authorize_url_uses_observed_parameters() -> None:
    req = oidc.build_authorize_url(AppConfig())
    params = _params(req.url)
    assert params["client_name"] == "O2CLOUD_WEB"
    assert params["client_id"] == "7f8afae4-30e7-4591-b4a8-4fc08d545d1d"
    assert params["scope"] == "openid"
    assert params["acr_values"] == "2"
    assert params["redirect_uri"] == "https://cloud.o2online.es/sapi/login/oauth"
    assert params["response_type"] == "code"
    assert req.state and req.nonce


def test_build_authorize_url_honours_supplied_state_nonce() -> None:
    req = oidc.build_authorize_url(AppConfig(), state="st8", nonce="nc9")
    assert req.state == "st8"
    assert req.nonce == "nc9"
    assert _params(req.url)["state"] == "st8"


def test_parse_redirect_extracts_code() -> None:
    url = "https://cloud.o2online.es/sapi/login/oauth?code=AUTHCODE&state=st8"
    assert oidc.parse_redirect(url, expected_state="st8") == "AUTHCODE"


def test_parse_redirect_state_mismatch_raises_auth_error() -> None:
    url = "https://cloud.o2online.es/sapi/login/oauth?code=AUTHCODE&state=evil"
    with pytest.raises(AuthError):
        oidc.parse_redirect(url, expected_state="st8")


def test_parse_redirect_missing_code_raises_auth_error() -> None:
    url = "https://cloud.o2online.es/sapi/login/oauth?state=st8"
    with pytest.raises(AuthError):
        oidc.parse_redirect(url, expected_state="st8")


def test_code_exchange_is_pending_phase1() -> None:
    with pytest.raises(NotImplementedYetError):
        oidc.exchange_code_for_session(AppConfig(), "code", state="st8")
