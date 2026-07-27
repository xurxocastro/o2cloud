# Architecture

## 1. How to read this document

Audience: contributors. This document captures the big picture that spans multiple files — the
layering, the authentication model, and the reverse-engineered SAPI contract. Field-level detail
lives in the code; the observed API lives in [`api-reference.md`](api-reference.md).

## 2. Overview

`o2cloud` is a scriptable, agent-friendly CLI for **O2 Cloud** (Telefónica España), whose backend is
**Funambol OneMediaHub** reached over an undocumented **SAPI**. There is no official API or SDK; the
contract was reverse-engineered from web traffic and static analysis of the Android app, and is
documented in [`api-reference.md`](api-reference.md) and [`apk-analysis.md`](apk-analysis.md). Every
command speaks JSON (`--json`) with a frozen exit-code contract so that agents and scripts can drive
it reliably.

## 3. Technology stack

Python ≥ 3.11 · `httpx` (transport) · `typer` + `rich` (CLI) · `pydantic` / `pydantic-settings`
(models and config) · `keyring` (secrets) · `platformdirs` · `tenacity` (retry). The optional
`browser` extra adds `playwright` for browser-assisted login. Development tooling: `ruff`, `mypy`,
`pytest` (with `respx`). The project is managed with `uv` and installed as a tool
(`uv tool install`), exposing the `o2cloud` console entry point.

## 4. Project structure

```
src/o2cloud/
  cli.py                 Typer app: global --json/--verbose/--quiet/--profile/--version, help, wiring
  commands/              one module per command group (auth, account, files, sync, share, trash, config)
  service.py             use-case orchestration (list/upload/download/sync, conflict policy)
  sync.py, paths.py      three-way sync engine; remote-path <-> folder-id resolution
  api/                   SAPI client + typed models
    client.py            httpx transport: auth, envelope parsing, retry, error mapping, upload/download
    auth.py quota.py media.py folders.py trash.py share.py   resource wrappers
    models.py            pydantic models (extra="allow" — tolerant to sparse or richer real responses)
  auth/
    oidc.py              login orchestration + validationKey/cookie extraction and persistence
    browser.py           Playwright browser-assisted login (optional; harvests httpOnly JSESSIONID)
  config.py secrets.py session.py logging.py errors.py output.py state.py   infrastructure
tests/                   unit tests (mocked SAPI via respx; fake browser) — no live network in CI
docs/                    architecture, API reference, APK analysis, agent usage, and testing guides
```

## 5. Core architecture principles

Clean layering **CLI -> service -> api -> infrastructure**. The API client is dependency-injected so
the CLI stays thin and everything is unit-testable against mocked HTTP. Secrets never touch ordinary
files (keyring or environment only). Untrusted SAPI responses are parsed with pydantic. Only the
endpoints documented in the API reference are used — no invented paths.

## 6. Build system and toolchain

`uv sync --extra dev [--extra browser]`; gate: `uv run ruff check .` · `uv run ruff format --check .`
· `uv run mypy src` · `uv run pytest -q`. Install: `uv tool install --editable .` (add
`--with playwright` for browser login).

## 7. Configuration

`config.py` (`pydantic-settings`): non-secret settings (base URL `cloud.o2online.es`, upload host
`upload.cloud.o2online.es`, user-agent, device id, request rate) are loaded from a TOML file in the
platform config directory, with `O2CLOUD_*` environment overrides, namespaced per `--profile`.
Secrets (`token`, `cookie`, credentials) are handled by `secrets.py` via the keyring
(`o2cloud:<profile>`) or `O2CLOUD_*` environment variables.

## 8. Authentication (the crux)

SAPI accepts two schemes (confirmed via static analysis; see [`apk-analysis.md`](apk-analysis.md)):

- **validationKey scheme (used here):** every call sends the `JSESSIONID` **httpOnly** session cookie
  **plus** `validationKey` (as a cookie and a `?validationkey=` query parameter). **Both are
  required** — the token alone returns 401.
- **OAuth2 bearer scheme** (`Authorization: oauth <b64 access_token>`, silent-refreshable) — **not
  used**: its client credentials come from a runtime remote configuration that cannot be extracted
  from the app.

Login paths (`auth/oidc.py`): (1) **browser** (`auth/browser.py`, Playwright) opens the real login
page, the user completes MobileConnect/SMS, and the CLI harvests the cookies including the httpOnly
`JSESSIONID`; (2) **manual import** (`--import-cookie` / `O2CLOUD_COOKIE`) from a browser DevTools
"Copy as cURL". There is no silent refresh (see [`apk-analysis.md`](apk-analysis.md)) — re-run
`login` on expiry.

## 9. SAPI surface (observed)

Base `https://cloud.o2online.es/sapi`. Envelopes: success `{data, responsetime}` / error
`{error{code,message,parameters,cause}, responsetime}` (an error may arrive with HTTP 200).
Key operations: quota `GET /media?action=get-storage-space`; account `GET /profile?action=get`;
folders `POST /media/folder?action=get`; media list `GET /media?action=get` (sparse); detail
`POST /media/file?action=get {data:{files:[{id}]}}` (includes `url`); download = GET the signed
relative `url` made absolute; upload = multipart to the upload host (`data` + `file` parts,
`YYYYMMDDThhmmssZ` dates); delete `POST /media/file?action=delete {data:{files:[id]}}`; server-side
copy `action=copy`. The full map is in [`api-reference.md`](api-reference.md).

## 10. Error handling and exit codes

`errors.py` maps a typed hierarchy to a frozen exit-code table (0 ok · 1 usage · 2 auth · 3 not
found · 4 conflict · 5 network · 6 rate-limited · 7 quota · 8 partial batch). `output.py` renders the
JSON success/error/batch envelopes (JSON only on stdout; logs and progress on stderr) and redacts
secrets.

## 11. Testing strategy

CI runs unit tests only: SAPI is mocked with `respx` and the browser is mocked with a fake session
and fake clock. The live end-to-end path (real login/upload/download) is verified manually, since it
needs a human for the SMS step. See [`testing.md`](testing.md).

## 12. Security considerations

Secrets live in the keyring or environment only, never in files or logs (a redacting log filter plus
envelope redaction enforce this). TLS verification is on (httpx default). Download filenames are
sanitized to a basename confined to the destination directory (path-traversal defense). No
`shell=True`, `eval`, or `pickle`. See [`../SECURITY.md`](../SECURITY.md).

## 13. Distribution

Distributed as a Python package / `uv` tool; there is no server component. Users install locally and
authenticate against their own O2 account.
