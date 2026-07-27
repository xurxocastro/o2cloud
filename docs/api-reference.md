# O2 Cloud — Observed API Reference

> Reverse-engineered reference for the `o2cloud` client, compiled from direct observation of the web
> portal `cloud.o2online.es` against a live authenticated session, plus static analysis of the Android
> app. There is no official, published API. No secrets are recorded here.
>
> Coverage: the read API and the core mutations (upload, download, delete, folder operations) are
> confirmed against live traffic. A few areas (labels/albums, search, share links) remain best-effort
> and are marked where relevant.

## Backend platform: Funambol OneMediaHub (SAPI)

The OAuth `redirect_uri` is **`https://cloud.o2online.es/sapi/login/oauth`**. The `/sapi/` path is the
Funambol **SAPI** (Server API) namespace, so the backend is **Funambol OneMediaHub**, consistent with
Telefónica's long-standing Funambol relationship (Movistar Cloud). The client is built around the SAPI
resource model.

## Authentication: federated OpenID Connect (not a plain SAPI password POST)

Clicking "Acceder" on `cloud.o2online.es/login` redirects to O2's identity provider. Authentication is
an **OIDC / OAuth2 Authorization-Code flow**, followed by a code-to-session exchange at SAPI:

| Parameter | Observed value |
| --- | --- |
| Authorization server | `https://t3.o2online.es/acceso/` (Mi O2 identity — "Login App O2") |
| Login UI route | `#/accessUserPassO2` (a username/password path exists) — **default screen is phone number + SMS code** |
| `client_name` | `O2CLOUD_WEB` |
| `client_id` | `7f8afae4-30e7-4591-b4a8-4fc08d545d1d` (public web-client id) |
| `scope` | `openid` |
| `acr_values` | `2` (strong auth / step-up → **SMS OTP**) |
| `prompt` | `login+consent` |
| `display` | `page` |
| `response` handling | the IdP redirects to `redirect_uri` with an auth `code` + `state` |
| `redirect_uri` | `https://cloud.o2online.es/sapi/login/oauth` |
| `nonce`, `state` | per-session random (CSRF / replay protection) |
| custom | `vip_conf_mode=app` |

**Flow (observed):**

```
1. GET  cloud.o2online.es/login                     -> landing ("Acceder")
2. ->   t3.o2online.es/acceso/#/accessUserPassO2?... -> OIDC authorize (client_id=O2CLOUD_WEB, scope=openid, acr_values=2)
3. User authenticates at the Mi O2 IdP:
        phone number -> SMS one-time code   (default),  OR  username (DNI) / password  (with SMS step-up)
4. IdP -> 302 -> cloud.o2online.es/sapi/login/oauth?code=<authcode>&state=<state>
5. SAPI exchanges the code and establishes a SAPI session (cookie)
6. The web app calls /sapi/* with that session
```

Because `acr_values=2` forces an **SMS OTP**, a CLI cannot log in non-interactively with DNI +
password; the SMS one-time code is mandatory.

## Token mechanism (confirmed live)

- **Two credentials are required together:**
  1. **`JSESSIONID`** — the servlet **session cookie** (httpOnly), set at OIDC login. This is the
     primary session credential. It is **invisible to JavaScript** (`document.cookie` cannot read it)
     and to the CLI unless captured from the browser's request `Cookie` header.
  2. **`validationKey`** — a 32-hex token, sent both as a cookie **and** as `?validationkey=` on every
     call (an anti-CSRF / secondary token).
- **Proven:** `validationKey` alone (cookie + query) returns **HTTP 401** from curl/CLI but **200**
  in-browser; `JSESSIONID + validationKey` (cookie) returns **200** from curl/CLI. Token-only replay
  does not work.
- Client state is cached in `localStorage['omhls']` (plus `omhls.fingerprintKey`) — "OMH" =
  OneMediaHub.
- **CLI auth:** `o2cloud login --import-cookie '<full Cookie header>'` captured from a logged-in
  `/sapi/*` request in DevTools (the `-b '…'` of "Copy as cURL") must contain `JSESSIONID` +
  `validationKey`. The full cookie header is stored in the keyring and replayed on every request;
  `validationkey` is also sent as the query parameter. Re-run `login` when a request returns 401
  (session expiry). The browser-assisted `o2cloud login` automates this capture.

## Envelopes (confirmed)

- **Success:** `{ "data": { … }, "responsetime": <epoch-ms> }`
- **Error:** `{ "error": { "code": "…", "message": "…", "parameters": [], "cause": "…" }, "responsetime": <epoch-ms> }`
  (the HTTP status may still be `200` with an `error` body — the client must branch on `data` vs
  `error`.)

## Read endpoints (confirmed against a live session)

- **Quota / storage** — `GET /sapi/media?action=get-storage-space&softdeleted=true`
  → `data:{ quota, free, used, softdeleted, nolimit(bool), individual:{used,softdeleted} }` (bytes).
- **Account / profile** — `GET /sapi/profile?action=get`; extras: `POST /sapi/profile/properties?action=get`,
  `GET /sapi/profile/fields?action=list`, polling `GET /sapi/profile/changes?action=get`.
- **Subscription** — `GET /sapi/subscription?action=get`; **plan** `GET /sapi/subscription/plan?action=get`
  → `data.plans[]{ name, price, currency, period, quota, nolimit }`; `GET /sapi/subscription/history?action=get`.
- **Folder listing** — `POST /sapi/media/folder?action=get` (JSON body optional; returns root)
  → `data.folders[]{ name, id(number), status, magic(bool), offline(bool), creationdate, date(epoch-ms) }`.
  ("magic" = Funambol auto-folders, e.g. Pictures/Videos.)
- **Media/file listing** — `GET /sapi/media?action=get&limit=N` → `data:{ media[], more(bool) }` (`more`
  = paginate).
- **Media sets** — `GET /sapi/media/set?action=list-media-sets` → `data.links[]`.
- **Labels / albums** — `POST /sapi/label?action=get&limit=100&shared_items=true` (exact body still to
  confirm; the web app sends a specific payload — recapture when albums exist).
- Miscellaneous: `GET /sapi/features`, `GET /sapi/system/information?action=get`,
  `GET /sapi/system/country?action=get`, `POST /sapi/family?action=get`,
  `GET /sapi/externalservice?action=get`, `POST /sapi/link?action=get`,
  `GET /sapi/media/picoftheday?action=get`.

## Media item schema (confirmed)

- **Listing** `/sapi/media?action=get&limit=N` returns **sparse** items: `{ id, date(epoch-ms),
  mediatype("file"|"picture"|"video"|"audio"), status("U"=uploaded/valid), userid }`.
- **Detail (confirmed live)** — `POST /sapi/media/file?action=get {data:{files:[{id}]}}` →
  `data.files[0]` with `{ id, url, date, creationdate, modificationdate, uploaded, size, name,
  mediatype, status, etag, softdeleted }`. (`POST /sapi/media?action=get {data:{ids:[{id}]}}` returns
  error `MED-1000` — do not use that form.)
- **Download (confirmed live)** — the detail **`url`** is a **host-relative signed path**:
  `/sapi/download/file?action=get&k=<signature>&node=<n>`. The `k=` token **self-authenticates**. Make
  it **absolute** (`https://cloud.o2online.es` + path) and GET it → 200, file bytes,
  `Content-Disposition`. **Gotcha:** never fetch the relative `/sapi/…` path via an httpx client whose
  `base_url` ends in `/sapi` — it becomes `/sapi/sapi/download/file`, and the server returns the SPA
  HTML shell (200), not the file. (`action=export` is a share/zip-link generator, not a direct
  download.)

## Mutations (captured via a controlled test upload/delete)

- **Upload (confirmed live)** — `POST https://upload.cloud.o2online.es/sapi/upload?action=save`
  (**dedicated upload host**), body **multipart `FormData`** with **two parts**: `data` = JSON
  `{"data":{name,size,modificationdate,creationdate,…}}` and `file` = the raw bytes. Header
  **`X-deviceid: <deviceid>`**. **Date format:** `modificationdate`/`creationdate` MUST be the compact
  UTC string **`YYYYMMDDThhmmssZ`** — epoch-ms is **rejected** with `COM-1008`. **Response JSON:**
  `{ success, id, etag, status, type }` — `id` = new item id, `etag` = validator. **Eventual
  consistency:** after upload the item does **not** appear in `GET /sapi/media?action=get` immediately
  (a few seconds of validation/processing); poll before expecting it in a listing. The session cookies
  (`JSESSIONID`) apply to the upload subdomain too (a host-agnostic cookie jar). Post-upload
  choreography: `POST /sapi/media?action=get-validation-status {data:{ids:[{id}]}}` (virus/processing
  check → `{data:{ids:[{id,status}]}}`), then `GET /sapi/profile/changes?action=get` reports
  `data.file.U:[id]` (U = uploaded).
- **Delete (permanent)** — `POST /sapi/media/file?action=delete` body `{ "data": { "files": [<id>, …] } }`
  → success envelope; removes bytes immediately. Per-type variants exist
  (`media/picture|video|audio?action=delete`). **Soft-delete (trash)** = `action=softdelete`.
- **Download (confirmed)** — get item detail (`POST /sapi/media/file?action=get {data:{files:[{id}]}}`),
  then GET its **`url`** field with `?validationkey=` appended → file bytes + `Content-Disposition`.
  `action=export` is a **share/zip-link** generator (not a direct download). Folder zip:
  `folder?action=zip`. Thumbnails: `GET /sapi/download/thumbnail?action=get&fdoid=<id>`.
- **mkdir / rename folder** — `POST /sapi/media/folder?action=save`. **Delete folder** = `action=delete`;
  **soft** = `action=softdelete`; **zip download** = `action=zip`; **list** = `action=list`.
- **Move item between folders** — `/sapi/media/folder?action=add-item` / `action=remove-item`.
- **Copy (server-side, no download + reupload needed)** — `POST /sapi/media/file?action=copy`.
- **File versioning** — `/sapi/media/revision?action=get` / `action=restore`.
- **Trash** — `/sapi/media/trash`, `/sapi/trash/folder` (restore/empty — parameters to confirm).
- **Albums / shares** — `/sapi/media/set?action=save|get|delete|list-media-sets`; `/sapi/label?action=get`.
- **Search** — no obvious dedicated server endpoint yet; the client falls back to a client-side filter
  over listings until one is confirmed.

## Full action map (from the app bundle — resources × actions)

`media/file`: get, count, delete, copy, export · `media/picture|video|audio`: get, count, delete, export ·
`media/folder`: get, save, list, delete, softdelete, add-item, remove-item, zip · `media/folder/root`: get ·
`media/revision`: get, restore · `media/set`: get, save, delete, list-media-sets · `media/trash`, `trash/folder` ·
`download/thumbnail`: get · plus profile / subscription / system / link / contact / features (read).

## Client auth strategy

A CLI cannot authenticate with DNI + password non-interactively, because the IdP requires an **SMS
OTP** (`acr_values=2`). Options, best first:

1. **Browser-assisted login with session reuse (recommended).** `o2cloud login` opens the real Mi O2
   OIDC page; the user enters credentials + SMS code; the CLI captures the resulting SAPI session
   cookies (including the httpOnly `JSESSIONID`) and stores them in the OS keyring. This is the most
   robust path given SMS 2FA.
2. **Reuse the mobile app's long-lived token.** The mobile app persists a long-lived token after the
   first SMS login. Recovering that token/refresh mechanism is not feasible from a laptop CLI (see
   [`apk-analysis.md`](apk-analysis.md)).
3. **Manual token/cookie import.** `o2cloud login --import-cookie` accepts a SAPI session captured from
   a browser DevTools session — a pragmatic fallback that needs no Playwright.

## Fingerprints (for app-mimicking headers)

- IdP host `t3.o2online.es/acceso/`, assets under `/acceso/images`, font `OnAir-Regular.woff2`.
- SAPI host `cloud.o2online.es`, namespace `/sapi/`.
