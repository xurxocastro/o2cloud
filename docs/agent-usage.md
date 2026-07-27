# Driving `o2cloud` from an AI agent (or any script)

`o2cloud` is built to be driven programmatically: a stable JSON contract, frozen exit codes,
env-var auth, and no interactive prompts under `--json`. This is the reference for consuming it.

## 1. Golden rules
- Always pass **`--json`**. It forces non-interactive mode and emits one JSON object on **stdout**;
  logs/progress go to **stderr**. Parse stdout, branch on the **exit code**.
- Provide credentials via **environment variables** (below) so nothing is interactive.
- Treat exit codes as the primary signal; the JSON `error.code` is the secondary, finer signal.

## 2. Output envelopes (stdout, with `--json`)
**Single success**
```json
{ "ok": true, "command": "quota", "data": { … } }
```
**Single error**
```json
{ "ok": false, "command": "ls", "error": { "code": "auth", "message": "…", "detail": { … } } }
```
**Batch** (upload/download/rm of several items) — `data` is always present, even on failure:
```json
{ "ok": false, "command": "upload",
  "data": [ { "target": "a.txt", "status": "ok",      "id": "…", "etag": "…" },
            { "target": "b.txt", "status": "conflict" },
            { "target": "c.txt", "status": "failed", "code": "network", "message": "…" } ],
  "error": { "code": "partial_failure", "message": "…", "counts": { … } } }
```
Per-item `status` ∈ `ok | skipped | conflict | failed`. `skipped` = intentional (`--skip`);
`conflict` = an unresolved destination collision (use `--force`/`--rename`/`--skip`).

## 3. Exit codes (frozen — safe to hard-code)
| Code | Meaning | Typical agent reaction |
|---|---|---|
| `0` | success | continue |
| `1` | usage / generic | fix the invocation |
| `2` | **auth** | session expired → trigger human re-login (see §5) |
| `3` | not found | the remote path/id doesn't exist |
| `4` | destination conflict | retry with `--force` / `--rename` / `--skip` |
| `5` | network / transport | retry with backoff |
| `6` | rate-limited (HTTP 429) | back off, retry later |
| `7` | insufficient quota | stop; free space |
| `8` | partial batch failure | inspect per-item `status` in `data` |

Batch aggregation: homogeneous all-failed → that cause's code; mixed failures → `8`; worst-case
conflict → `4`; all ok/skipped → `0`.

## 4. Invocation example
```python
import json, subprocess, os

def o2(*args, cookie, token):
    env = {**os.environ, "O2CLOUD_COOKIE": cookie, "O2CLOUD_TOKEN": token}
    p = subprocess.run(["o2cloud", *args, "--json"], env=env,
                       capture_output=True, text=True)
    out = json.loads(p.stdout) if p.stdout.strip() else {}
    return p.returncode, out

code, res = o2("ls", "/", cookie=COOKIE, token=TOKEN)
if code == 2:
    request_human_relogin()          # auth expired
elif code == 0:
    for item in res["data"]:
        print(item.get("name") or item["id"], item["mediatype"])
```

## 5. Auth for agents (the one human-in-the-loop)
O2's session is a `JSESSIONID` cookie + `validationKey`, behind **SMS 2FA**, and there is **no
silent refresh** (the app's OAuth-refresh path needs a runtime-fetched client secret and SIM-based
MobileConnect — not reproducible headless; see `apk-analysis.md`). So:

- **Headless while valid:** inject the captured session and run fully unattended:
  - `O2CLOUD_COOKIE` = the full `Cookie` header (`JSESSIONID=…; validationKey=…`)
  - `O2CLOUD_TOKEN`  = the `validationKey` (32 hex)
  These override the keyring; nothing touches disk.
- **On `exit 2`:** the session expired. A **human** must re-authenticate once (`o2cloud login`
  opens a browser for credentials + SMS), then the new cookie/token is re-injected. A servlet
  session typically lasts hours, so this is periodic, not per-call — but it is **not**
  fire-and-forget forever.

Pattern: human logs in → export `O2CLOUD_COOKIE`/`O2CLOUD_TOKEN` into the agent's environment →
agent runs until it sees `exit 2` → agent signals for a fresh login.

## 6. Command cheatsheet (all accept `--json`)
`login` · `logout` · `whoami` · `account` · `quota` · `ls [remote]` · `tree [remote]` ·
`stat <remote>` · `upload <local…> --to <remote>` · `download <remote…> --to <local>` ·
`mkdir` · `mv` · `cp` · `rm [--permanent]` · `search` · `sync` · `share` · `trash` · `config`.

Multi-source `upload`/`download` require `--to`. Conflict flags: `--force` / `--skip` / `--rename`.

## 7. Gotchas
- **`ls` names:** `ls`/`tree` resolve file names by default (a batch detail call). For maximum
  speed on huge folders where you only need ids, pass **`--no-detail`** (files then list by `id`).
- **Eventual consistency:** after `upload`, a file may take a few seconds to appear in `ls`. Poll.
- **Operate by id when unsure:** `download`/`rm`/`stat` accept a remote name **or** the item `id`;
  ids are unambiguous and always resolvable.
- **`search`/`share`:** best-effort (client-side filter / limited capture) — verify results.
