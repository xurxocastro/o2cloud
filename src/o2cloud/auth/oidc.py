"""OIDC login orchestration and session persistence.

Implements the confirmed authentication flow from ``docs/api-reference.md``.
The authorize-URL builder, redirect parsing, cookie/validationKey extraction,
and browser-assisted login are all functional. The direct code-to-session
exchange (:func:`exchange_code_for_session`) is not implemented — browser-assisted
login is used instead, since a silent OAuth exchange is not feasible (see
``docs/apk-analysis.md``).

Confirmed flow (see ``docs/api-reference.md`` § Authentication)
--------------------------------------
1. ``GET  cloud.o2online.es/login``  → landing ("Acceder").
2. Redirect to the Mi O2 IdP authorize endpoint at
   ``https://t3.o2online.es/acceso/`` with:
   ``client_name=O2CLOUD_WEB``, ``client_id=7f8afae4-...``, ``scope=openid``,
   ``acr_values=2`` (**forces SMS OTP**), ``prompt=login+consent``,
   ``display=page``, ``redirect_uri=https://cloud.o2online.es/sapi/login/oauth``,
   plus per-session ``state`` + ``nonce`` and custom ``vip_conf_mode=app``.
3. The **user** completes credentials + SMS OTP in a real browser (the agent must
   never type the password nor can it receive the SMS code).
4. IdP → 302 → ``.../sapi/login/oauth?code=<authcode>&state=<state>``.
5. SAPI exchanges the code for a session (cookie/JWT). **[UNVERIFIED shape]**
6. Subsequent ``/sapi/*`` calls reuse that session.

Because ``acr_values=2`` mandates SMS OTP, non-interactive DNI+password auth is
impossible; the CLI drives the real login page and captures the resulting SAPI
token. ``--import-cookie`` is the manual stop-gap; app long-lived-token reuse
(Path B) is the headless goal.
"""

from __future__ import annotations

import re
import secrets as _secrets
import urllib.parse
from dataclasses import dataclass

from ..config import AppConfig
from ..errors import AuthError, NotImplementedYetError
from ..secrets import SecretStore
from ..session import SessionMetadata, save_session

# The Funambol ``validationKey`` is 32 lowercase-hex chars (memo § Token mechanism).
VALIDATION_KEY_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass
class AuthorizeRequest:
    """A built authorize request: the URL to open plus the CSRF/replay nonces.

    ``state`` and ``nonce`` must be retained by the caller to validate the
    redirect that comes back from the IdP.
    """

    url: str
    state: str
    nonce: str


def _new_nonce(num_bytes: int = 24) -> str:
    return _secrets.token_urlsafe(num_bytes)


def build_authorize_url(
    config: AppConfig,
    *,
    state: str | None = None,
    nonce: str | None = None,
) -> AuthorizeRequest:
    """Construct the Mi O2 OIDC authorize URL from observed parameters.

    This is a pure function (no network). The exact authorize *path* under
    ``oidc_authorize_base`` is still **[UNVERIFIED]** — the observed capture only
    showed the SPA route ``#/accessUserPassO2``. We therefore attach the query to
    the configured base and leave a TODO to pin the real ``/authorize`` path once
    captured.
    """
    state = state or _new_nonce()
    nonce = nonce or _new_nonce()

    params = {
        "client_name": config.oidc_client_name,
        "client_id": config.oidc_client_id,
        "scope": config.oidc_scope,
        "acr_values": config.oidc_acr_values,  # "2" → SMS OTP step-up
        "prompt": "login consent",
        "display": "page",
        "response_type": "code",
        "redirect_uri": config.oidc_redirect_uri,
        "state": state,
        "nonce": nonce,
        "vip_conf_mode": "app",
    }
    # TODO(live-capture): confirm the authorize endpoint path (the reference shows
    # only the SPA route "#/accessUserPassO2"); the query set above is derived from
    # the observed OAuth handshake in docs/api-reference.md.
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    url = f"{config.oidc_authorize_base.rstrip('/')}/authorize?{query}"
    return AuthorizeRequest(url=url, state=state, nonce=nonce)


def parse_redirect(redirect_url: str, *, expected_state: str) -> str:
    """Extract and validate the auth ``code`` from the IdP redirect.

    Validates ``state`` to defeat CSRF/replay. Returns the authorization code.
    """
    parsed = urllib.parse.urlparse(redirect_url)
    qs = urllib.parse.parse_qs(parsed.query)
    returned_state = (qs.get("state") or [""])[0]
    if returned_state != expected_state:
        from ..errors import AuthError

        raise AuthError("OIDC state mismatch — possible CSRF/replay; aborting login")
    code = (qs.get("code") or [""])[0]
    if not code:
        from ..errors import AuthError

        raise AuthError("no authorization code in redirect URL")
    return code


def exchange_code_for_session(
    config: AppConfig,
    code: str,
    *,
    state: str,
) -> SessionMetadata:
    """Exchange the auth ``code`` at ``/sapi/login/oauth`` for a SAPI session.

    Not implemented: browser-assisted login is used instead. Implementing this
    would require confirming the exchange request/response and the resulting token
    shape (cookie vs JWT), expiry, and account id, then persisting the secret via
    :class:`SecretStore` and returning only non-secret :class:`SessionMetadata`.
    """
    raise NotImplementedYetError("login", detail={"stage": "code-exchange"})


def extract_validation_key(raw: str) -> str:
    """Pull a 32-hex ``validationKey`` out of a raw token or cookie string.

    Accepts any of: the bare key (``deadbeef…``); a ``validationKey=<key>`` cookie
    pair (case-insensitive), optionally within a larger ``Cookie:`` header with
    ``;``-separated pairs; or a URL/query containing ``validationkey=<key>``.
    Raises :class:`AuthError` if no well-formed key is found.
    """
    text = raw.strip()
    candidate = text

    # cookie / query form: find validationkey=<value> anywhere, case-insensitive.
    match = re.search(r"validationkey\s*=\s*([0-9A-Fa-f]{32})", text, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1)
    else:
        # A lone ``key=value`` (no "validationkey" name) — take the value side.
        if "=" in candidate and " " not in candidate.split("=", 1)[0]:
            candidate = candidate.split("=", 1)[1].strip().strip(";")

    candidate = candidate.lower()
    if not VALIDATION_KEY_RE.match(candidate):
        raise AuthError(
            "could not find a valid 32-hex validationKey in the supplied value",
            detail={"expected": "32 lowercase-hex chars"},
        )
    return candidate


def extract_cookie_header(raw: str) -> str:
    """Return the ``Cookie`` header value to replay from a raw import string.

    O2's SAPI session is authenticated by the **``JSESSIONID``** servlet cookie
    (httpOnly) plus the ``validationKey``; the token alone is not sufficient
    (confirmed live — see ``docs/api-reference.md`` § Token mechanism). This
    accepts the cookie string a user copies from browser devtools (the ``-b '…'``
    value of a "Copy as cURL", optionally prefixed by ``Cookie:``), preserving
    ``JSESSIONID`` and every other pair, and falls back to a bare
    ``validationKey=<key>`` when only the key is supplied.
    """
    text = raw.strip()
    # Pull the cookie string out of a pasted cURL's -b/--cookie clause if present.
    curl_match = re.search(r"(?:-b|--cookie)\s+(['\"])(.*?)\1", text, flags=re.DOTALL)
    if curl_match:
        text = curl_match.group(2).strip()
    # Strip a leading "Cookie:" label.
    label = re.match(r"(?i)cookie:\s*(.+)", text, flags=re.DOTALL)
    if label:
        text = label.group(1).splitlines()[0].strip()
    # A cookie-pairs string (name=value; …): keep it verbatim if it carries a key.
    if re.search(r"[^\s=;]+=[^;]+", text):
        extract_validation_key(text)  # raises AuthError if no validationKey present
        return text.rstrip(";").strip()
    # Otherwise treat it as a bare key.
    key = extract_validation_key(text)
    return f"validationKey={key}"


def _persist(
    config: AppConfig,
    secret_store: SecretStore,
    key: str,
    *,
    cookie: str,
    profile: str,
) -> SessionMetadata:
    """Store the validationKey (query token) + full session cookie, and metadata."""
    # ``token`` → the validationkey query param; ``cookie`` → the full Cookie
    # header (JSESSIONID + validationKey + …) the transport replays each request.
    secret_store.store_token(key, cookie=cookie)
    meta = SessionMetadata(profile=profile, base_url=config.base_url, keyring_key="token")
    save_session(meta)
    return meta


def import_token(
    config: AppConfig, secret_store: SecretStore, token: str, *, profile: str
) -> SessionMetadata:
    """Import a bare ``validationKey`` and persist it.

    NOTE: the validationKey alone does **not** authenticate against O2's SAPI —
    the ``JSESSIONID`` session cookie is also required. Prefer ``--import-cookie``
    with the full browser Cookie header. This path stores only a
    ``validationKey=<key>`` cookie and is kept for completeness / testing.
    """
    key = extract_validation_key(token)
    return _persist(config, secret_store, key, cookie=f"validationKey={key}", profile=profile)


def import_cookie(
    config: AppConfig, secret_store: SecretStore, cookie: str, *, profile: str
) -> SessionMetadata:
    """Import the full SAPI session **cookie** header captured from devtools.

    This is the robust, fully-supported login path. Pass the ``Cookie`` request
    header value from a logged-in ``/sapi/*`` request (e.g. the ``-b '…'`` of a
    "Copy as cURL") — it must include ``JSESSIONID`` and ``validationKey``. Both
    are stored in the keyring; only non-secret metadata is written to disk.
    """
    key = extract_validation_key(cookie)
    header = extract_cookie_header(cookie)
    return _persist(config, secret_store, key, cookie=header, profile=profile)


def login(
    config: AppConfig,
    secret_store: SecretStore,
    *,
    profile: str,
    timeout_s: float = 300.0,
    headless: bool = False,
) -> SessionMetadata:
    """Browser-assisted login: open a real browser, harvest the session cookies.

    Delegates to :mod:`o2cloud.auth.browser` (Playwright). The **user** completes login
    (MobileConnect / SMS / OIDC — the agent never types the password nor reads the OTP); the CLI
    reads the resulting cookies (incl. httpOnly ``JSESSIONID``) from the browser context and
    persists them via the same path as ``--import-cookie``. ``timeout_s``/``headless`` forward from
    the CLI. If Playwright is not installed, raises :class:`AuthError` with the install hint and
    the manual ``--import-cookie`` fallback (nothing regresses). See ``docs/apk-analysis.md``
    for why this is used instead of a headless OAuth refresh.
    """
    from . import browser

    if not browser.is_available():
        request = build_authorize_url(config)
        raise AuthError(
            "browser login needs Playwright (optional extra). " + browser.INSTALL_HINT,
            detail={"authorize_url": request.url, "install": browser.INSTALL_HINT},
        )
    cookie_header = browser.browser_login(config, timeout_s=timeout_s, headless=headless)
    key = extract_validation_key(cookie_header)
    header = extract_cookie_header(cookie_header)
    return _persist(config, secret_store, key, cookie=header, profile=profile)


__all__ = [
    "AuthorizeRequest",
    "VALIDATION_KEY_RE",
    "build_authorize_url",
    "parse_redirect",
    "extract_validation_key",
    "extract_cookie_header",
    "exchange_code_for_session",
    "login",
    "import_token",
    "import_cookie",
]
