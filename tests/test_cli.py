"""End-to-end CLI tests via Typer's CliRunner: help, version, JSON error paths."""

from __future__ import annotations

import json

import httpx
import respx
from typer.testing import CliRunner

from o2cloud import __version__
from o2cloud.cli import app
from o2cloud.secrets import SecretStore

runner = CliRunner()

TOKEN = "0123456789abcdef0123456789abcdef"  # placeholder validationKey (not real)
SAPI = "https://cloud.o2online.es/sapi"


def _json(stdout: str) -> dict:
    return json.loads(stdout)


def test_help_exits_zero_and_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "config" in result.stdout
    assert "upload" in result.stdout


def test_version_prints_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_ls_json_auth_error_when_no_token() -> None:
    # Wired command: with no stored validationKey the transport raises AuthError,
    # so ls returns the auth envelope + exit code 2 (not a stub error).
    result = runner.invoke(app, ["ls", "--json"])
    assert result.exit_code == 2
    payload = _json(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "ls"
    assert payload["error"]["code"] == "auth"


def test_json_flag_works_before_command_too() -> None:
    result = runner.invoke(app, ["--json", "whoami"])
    assert result.exit_code == 2
    payload = _json(result.stdout)
    assert payload["command"] == "whoami"
    assert payload["error"]["code"] == "auth"


def test_config_set_and_get_via_cli_json() -> None:
    set_res = runner.invoke(app, ["config", "set", "base_url", "https://cli.test", "--json"])
    assert set_res.exit_code == 0
    assert _json(set_res.stdout)["data"]["value"] == "https://cli.test"

    get_res = runner.invoke(app, ["config", "get", "base_url", "--json"])
    assert get_res.exit_code == 0
    assert _json(get_res.stdout)["data"] == {"base_url": "https://cli.test"}


def test_config_get_all_via_cli_json() -> None:
    result = runner.invoke(app, ["config", "get", "--json"])
    assert result.exit_code == 0
    data = _json(result.stdout)["data"]
    assert data["oidc_client_name"] == "O2CLOUD_WEB"
    assert "settable_keys" not in data


def test_upload_requires_to_with_multiple_sources() -> None:
    result = runner.invoke(app, ["upload", "a.txt", "b.txt", "--json"])
    assert result.exit_code == 1
    err = _json(result.stdout)["error"]
    assert err["code"] == "usage"
    assert "--to is required" in err["message"]


def test_upload_single_source_allows_missing_to() -> None:
    # Single source without --to is valid usage (not exit 1); it proceeds to the
    # service and fails on the missing local file (not_found), proving the usage
    # gate passed rather than a stub.
    result = runner.invoke(app, ["upload", "a.txt", "--json"])
    assert result.exit_code == 3
    payload = _json(result.stdout)
    assert payload["error"]["code"] == "not_found"
    assert payload["data"][0]["status"] == "failed"


def test_conflict_flags_are_mutually_exclusive() -> None:
    result = runner.invoke(app, ["mv", "a", "b", "--force", "--skip", "--json"])
    assert result.exit_code == 1
    assert _json(result.stdout)["error"]["code"] == "usage"


def test_sync_modes_are_mutually_exclusive() -> None:
    result = runner.invoke(app, ["sync", "local", "remote", "--up", "--down", "--json"])
    assert result.exit_code == 1
    assert _json(result.stdout)["error"]["code"] == "usage"


def test_share_and_trash_subcommands_need_auth() -> None:
    share = runner.invoke(app, ["share", "list", "--json"])
    assert share.exit_code == 2
    assert _json(share.stdout)["error"]["code"] == "auth"

    trash = runner.invoke(app, ["trash", "ls", "--json"])
    assert trash.exit_code == 2
    assert _json(trash.stdout)["error"]["code"] == "auth"


def test_human_error_output_non_json() -> None:
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 2
    assert "not authenticated" in result.stdout


# --- authed command paths (mocked SAPI) -------------------------------------
@respx.mock
def test_quota_json_returns_data_when_authenticated() -> None:
    SecretStore("default").set("token", TOKEN)
    respx.get(f"{SAPI}/media").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {"quota": 100, "free": 90, "used": 10, "nolimit": False},
                "responsetime": 1,
            },
        )
    )
    result = runner.invoke(app, ["quota", "--json"])
    assert result.exit_code == 0
    payload = _json(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "quota"
    assert payload["data"]["used"] == 10


def test_login_import_token_persists_and_reports_ok() -> None:
    result = runner.invoke(app, ["login", "--import-token", TOKEN, "--json"])
    assert result.exit_code == 0
    payload = _json(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["mode"] == "import-token"
    assert SecretStore("default").token == TOKEN


def test_login_browser_mode_is_auth_error_without_token() -> None:
    result = runner.invoke(app, ["login", "--json"])
    assert result.exit_code == 2
    assert _json(result.stdout)["error"]["code"] == "auth"


def test_logout_clears_session() -> None:
    SecretStore("default").set("token", TOKEN)
    result = runner.invoke(app, ["logout", "--json"])
    assert result.exit_code == 0
    assert SecretStore("default").token is None


def test_sync_dry_run_reports_plan_when_authenticated() -> None:
    # Empty local + empty remote (root needs no folder call) → empty plan.
    with respx.mock:
        SecretStore("default").set("token", TOKEN)
        respx.post(f"{SAPI}/media/folder").mock(
            return_value=httpx.Response(200, json={"data": {"folders": []}, "responsetime": 1})
        )
        respx.get(f"{SAPI}/media").mock(
            return_value=httpx.Response(
                200, json={"data": {"media": [], "more": False}, "responsetime": 1}
            )
        )
        result = runner.invoke(app, ["sync", ".", "/", "--dry-run", "--up", "--json"])
    assert result.exit_code == 0
    payload = _json(result.stdout)
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["direction"] == "up"
