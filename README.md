# o2cloud

[![CI](https://github.com/dbaratech/o2cloud/actions/workflows/ci.yml/badge.svg)](https://github.com/dbaratech/o2cloud/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A scriptable, agent-friendly command-line client for **O2 Cloud** — the personal-cloud storage of
O2 / Telefónica España (`cloud.o2online.es`). The backend is reached
through the API namespace at `https://cloud.o2online.es/sapi/`.

`o2cloud` gives you `ls`, `upload`, `download`, `sync`, `share`, `trash`, and more from the terminal,
with a stable `--json` output contract and frozen exit codes so scripts and AI agents can drive it
reliably.

## 🚀 Guía rápida para usar desde otro ordenador (Fork parcheado)

Este fork de **`xurxocastro/o2cloud`** contiene correcciones críticas sobre el paquete original que resuelven incompatibilidades reales con la API de O2 España (recursión infinita en árbol de carpetas, resolución de fotos, auto-creación de carpetas, tipado en subidas y filtros de archivos temporales de macOS).

### 1. Clonar e instalar en otro equipo

```bash
git clone https://github.com/xurxocastro/o2cloud.git
cd o2cloud

# Crear entorno virtual e instalar dependencias
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install playwright
playwright install chromium
```

### 2. Iniciar sesión (con verificación SMS)

Ejecuta el asistente interactivo:
```bash
python3 scripts/auto_login.py --email tu_email@ejemplo.com
```
Se abrirá una ventana de Chromium en tu pantalla con tu usuario precargado; introduce el SMS que recibas en tu teléfono y la sesión se guardará automáticamente en el sistema.

### 3. Sincronizar directorios

Para subir una biblioteca completa (evitando que el equipo se suspenda si estás en macOS):
```bash
./scripts/run_sync.sh "/ruta/a/tus/fotos" "/2026"
```

---

## Status and disclaimer

> **Unofficial interoperability client.** `o2cloud` is not affiliated with, endorsed by, or supported
> by O2 or Telefónica. There is no official public API; the client speaks an **undocumented
> API** reverse-engineered from observed traffic, so endpoints may change or break without notice.
>
> It is intended for an account owner to access **their own data**. You are responsible for complying
> with **O2's Terms of Service** and applicable law. **Use at your own risk.**

The full command set is implemented and verified end-to-end against a live account (including a
byte-exact upload/download cycle). Known limitations: after an upload a file may take a few seconds to
appear in listings (server-side validation); `search` and `share` are best-effort pending further
capture; and authentication has no silent refresh — a human re-runs `o2cloud login` (SMS) when the
session expires.

## Features

- Full file management: `ls`, `tree`, `stat`, `upload`, `download`, `mkdir`, `mv`, `cp`, `rm`.
- Named listings: `ls`/`tree` resolve file names and sizes (with a `--no-detail` fast path).
- Directory `sync` (`--up` / `--down` / `--two-way`, `--dry-run`, `--delete`).
- `share`, `trash`, `account`, and `quota` commands.
- Stable machine interface: `--json` envelopes and a frozen exit-code contract for scripts and agents.
- Secrets stored only in the OS keyring or `O2CLOUD_*` environment variables — never in files.
- Per-profile isolation to prevent wrong-account credential reuse.

## Install

The project targets **Python 3.11+** and is developed with [`uv`](https://docs.astral.sh/uv/).

### As a tool (recommended)

```bash
uv tool install o2cloud        # from PyPI once published, or:
uv tool install .              # from a checkout
o2cloud --help
```

### Browser login extra

Browser-assisted login uses Playwright, which is an optional extra:

```bash
uv tool install --with playwright --with-executables-from playwright .
playwright install chromium    # one-time Chromium download
```

### With pipx

```bash
pipx install .
o2cloud --help
```

## Authentication

O2's session requires the httpOnly **`JSESSIONID`** cookie **and** the `validationKey`; the token
alone returns 401. Login is federated OpenID Connect via Mi O2 (`t3.o2online.es/acceso`) and forces
**strong auth (SMS OTP)**, so it cannot be fully automated. There are two ways to log in:

### Browser login (recommended)

```bash
o2cloud login
```

A real browser window opens at the O2 login page; **you** complete the login (DNI/password + SMS —
the CLI never types your password nor reads the OTP). When login finishes, the CLI reads the cookies
(including the httpOnly `JSESSIONID`) from the browser and stores them in the OS keyring. On expiry,
run `o2cloud login` again. Flags: `--timeout <s>`, `--headless` (for tests only — cannot pass SMS).

Requires the `browser` extra (see Install). Why not a fully silent OAuth refresh? See
[`docs/apk-analysis.md`](docs/apk-analysis.md).

### Manual cookie import (fallback, no Playwright)

Log in at `cloud.o2online.es`, then in DevTools open **Network**, filter `sapi`, pick any request,
**right-click → Copy → Copy as cURL**, and import the cookie value:

```bash
o2cloud login --import-cookie '<the -b "…" cookie value>'   # must contain JSESSIONID + validationKey
```

Agents can also inject `O2CLOUD_COOKIE` and `O2CLOUD_TOKEN` directly (see
[`docs/agent-usage.md`](docs/agent-usage.md)).

No credentials are ever stored in files or in this repository. Secrets live only in the OS keyring or
in `O2CLOUD_*` environment variables.

## Usage

```bash
o2cloud --version
o2cloud quota --json
o2cloud ls / --json
o2cloud upload ./photo.jpg --to /Pictures --json
o2cloud download /Pictures/photo.jpg --to ./ --json
o2cloud rm /Pictures/photo.jpg --json
```

With `--json`, only the JSON result goes to **stdout**; logs and progress go to **stderr**, and the
command never prompts. Global options are accepted before **or** after the command:
`--json`, `--verbose/-v`, `--quiet/-q`, `--profile <name>`, `--version`.

### Command reference

| Command | Purpose |
| --- | --- |
| `login` / `logout` / `whoami` | authenticate, clear the session, show identity |
| `account` / `quota` | storage usage and plan details |
| `ls [remote]` / `tree [remote]` | list a folder / recursive listing (`--no-detail` for id-only) |
| `stat <remote>` | file/folder metadata |
| `upload <local...> [--to <remote>]` | upload files/dirs; `--to` required when >1 source; `--recursive`, `--force/--skip/--rename` |
| `download <remote...> [--to <local>]` | download; `--to` required when >1 source; `--force/--skip/--rename` |
| `mkdir <remote>` | create a folder |
| `mv <src> <dst>` / `cp <src> <dst>` | move/rename / copy; `--force/--skip/--rename` |
| `rm <remote>` | delete (to trash by default; `--permanent`) |
| `search <query>` | search (best-effort) |
| `share create/list/revoke` | share-link management |
| `trash ls/restore/empty` | trash management |
| `sync <local> <remote>` | directory sync (`--up/--down/--two-way`, `--dry-run`, `--delete`) |
| `config get [key]` / `config set <key> <value>` | manage local non-secret config |

## Using it from an agent or script

The machine interface is a stability contract:

- **Streams.** With `--json`, only the JSON result goes to stdout; logs go to stderr.
- **Success envelope:** `{"ok": true, "command": "<name>", "data": <result>}`.
- **Error envelope:** `{"ok": false, "command": "<name>", "error": {"code": "<slug>", "message": "...", "detail": {...}}}`.
- **Batch envelope:** `data` is a per-item array; each item carries a `status`
  (`ok | skipped | conflict | failed`). `ok` is `true` only when every item is `ok`/`skipped`.

See [`docs/agent-usage.md`](docs/agent-usage.md) for the full guide, including the environment-variable
auth pattern and human-in-the-loop renewal.

### Exit codes (frozen at 1.0)

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | generic / usage error |
| 2 | authentication failure |
| 3 | not found |
| 4 | destination conflict (non-clobber) |
| 5 | network / transport |
| 6 | rate limited (HTTP 429) |
| 7 | insufficient quota |
| 8 | partial batch failure |

**Batch aggregation precedence:** single item → that item's code; a batch with one outcome → that
outcome's code; a mixed batch → any hard `failed` ⇒ 8, else any `conflict` ⇒ 4, else 0.

## Configuration and secrets

- **Non-secret config** (base URL, user-agent, OIDC parameters, defaults) lives in a TOML file under
  the platform config directory, namespaced per profile. Override the location with
  `O2CLOUD_CONFIG_DIR`. Every `O2CLOUD_*` environment variable overrides the corresponding config key.
- **Secrets** live only in the OS keyring (service `o2cloud:<profile>`) or in the environment:
  `O2CLOUD_USERNAME`, `O2CLOUD_PASSWORD`, `O2CLOUD_TOKEN`, `O2CLOUD_COOKIE`. They are **never** written
  to files. See [`.env.example`](.env.example).
- **Profiles.** `--profile <name>` (default `default`) namespaces config, keyring entries, session
  metadata, and sync manifests by `(profile, base_url)` to prevent wrong-account credential reuse.

## Development

```bash
uv pip install -e ".[dev]"
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run mypy src                # type-check
uv run pytest -q               # tests
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full development workflow, and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design overview.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — architecture and design.
- [`docs/api-reference.md`](docs/api-reference.md) — the observed SAPI contract.
- [`docs/apk-analysis.md`](docs/apk-analysis.md) — Android app analysis and headless-feasibility verdict.
- [`docs/agent-usage.md`](docs/agent-usage.md) — driving `o2cloud` from an agent or script.
- [`docs/testing.md`](docs/testing.md) — testing guide.
- [`SECURITY.md`](SECURITY.md) — security policy and the legal/interoperability notice.

## License

[MIT](LICENSE) © 2026 David Baratech.
