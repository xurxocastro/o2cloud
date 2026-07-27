# O2 Cloud Android APK — Auth Analysis & Headless-Feasibility Verdict

> Static analysis of `es.o2online.cloud` **v2.0.8** (XAPK from apkpure, decompiled with jadx +
> apktool). Goal: decide whether a CLI can authenticate **headlessly / with silent refresh**
> (the app avoids re-SMS on every launch — how?), or whether we fall back to browser automation.
> **No secrets were extractable** (see verdict) — nothing sensitive is recorded here.

## App shape
- Core is the **Funambol OneMediaHub** client (`com.funambol.*`), same backend as the web
  (`cloud.o2online.es`, SAPI). Bundles the Dropbox SDK (the "Conecta tu Dropbox" feature — its
  `mPKCEManager`/`oauth2/token`/`access_token` strings are Dropbox's, not O2's) and the img.ly editor.
- `app_server_host = cloud.o2online.es`, `portal_url = https://cloud.o2online.es`,
  `custom_protocol_scheme = omh`, `oauth_login_screen_type = mobileconnect`.

## Two SAPI auth schemes (from `com.funambol.sapi.network.interceptor`)
1. **validationKey scheme** (`interceptor/a.java`) — what the **web** uses and what the CLI
   implements: `?validationkey=` query + `JSESSIONID` cookie. On 401 it **re-logs-in** via
   `/sapi/login?action=login` or `/sapi/mobile?action=signup` (needs credentials again → not silent).
2. **OAuth2 bearer scheme** (`interceptor/c.java`) — `Authorization: oauth <base64(access_token)>`.
   On 401 it **refreshes** the access token using a stored `refresh_token`. **This is the silent-
   refresh path.** Login/validate responses carry `access_token` + `refresh_token` + `expires_in`
   (`mobileconnect/model/ValidateTokens`) and the SAPI session `jsessionid` + `validationkey`
   (`mobileconnect/model/LoginResponse`).

## The OAuth2 token exchange (from `client/controller/ud.java`)
- Token requests POST to a configured endpoint with
  `Authorization: Basic base64(client_id:client_secret)` (`ud.J()`/`ud.X()`), bodies
  `grant_type=authorization_code…&redirect_uri=…&client_id=…&client_secret=…`.
- `client_id = config.U0()`, `client_secret = config.W0()`, token/exchange URLs = `config.B0()` etc.
  — all **methods on a runtime `Configuration` object**, NOT static values.

## Why headless refresh is NOT feasible for the CLI (the blocker)
- The OAuth2 URLs are **empty in `res/values/strings.xml`** (`oauth2_access_token_uri`,
  `oauth2_auth_token_uri`, `oauth2_redirect_uri`, `oauth2_scope`, `oauth2_revoke_token_url` are all
  `<string .../>`), and no `client_secret` is in `strings.xml` or `assets/`. They are delivered by a
  **server-side remote configuration fetched at runtime** during app init.
- The default login is **MobileConnect** (MSISDN/SIM header-enrichment over the mobile network) —
  **not reproducible** from a laptop CLI; the OAuth2 code flow uses a mobile redirect
  (`omh://` scheme / `/ui/html/clientoauth.html`), awkward to capture headlessly.
- To obtain `client_id`/`client_secret` we would need **dynamic capture** on a rooted device/emulator
  with a SIM + MITM proxy — out of scope for this environment — and the result would be a
  **server-rotatable secret**, making any CLI built on it fragile.

**Verdict: NOT feasible / not robust → use browser automation (Playwright).**

## Chosen path — Playwright browser-assisted login (v0.3.0)
`o2cloud login` launches a real (headed) Chromium via Playwright, the **user** completes login
(MobileConnect / SMS / OIDC — whatever O2 presents), and the CLI reads the resulting cookies from the
browser context (**including the httpOnly `JSESSIONID`**, which `context.cookies()` exposes but
`document.cookie`/devtools-copy cannot easily), then stores the `JSESSIONID + validationKey` cookie
header in the keyring — killing the devtools "Copy as cURL" kludge. Session lifetime = the servlet
session; on expiry, re-run `o2cloud login`. (Silent refresh would require the OAuth machinery above,
which we cannot obtain — documented here so we don't re-investigate.)
