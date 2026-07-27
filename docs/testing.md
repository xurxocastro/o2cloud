# Testing

The stack is **Python 3.11+** with **pytest**. Tests live in the top-level `tests/` directory and run
against the `o2cloud` package installed in editable mode. No live network is used in CI — the SAPI
client is mocked with `respx`, and the browser login is mocked with a fake session and clock.

## Test framework

- **Runner:** [`pytest`](https://docs.pytest.org/) (>= 8.0), configured in `pyproject.toml` under
  `[tool.pytest.ini_options]`.
- **Coverage:** [`pytest-cov`](https://pytest-cov.readthedocs.io/) (`[tool.coverage.*]`).
- **HTTP mocking:** [`respx`](https://lundberg.github.io/respx/) for the SAPI client (no live traffic
  in CI).
- **CLI testing:** Typer's `CliRunner` (`typer.testing.CliRunner`) for end-to-end command invocation,
  asserting exit codes and JSON envelopes.

## Running tests

Using `uv` (recommended):

```bash
# Run all tests
uv run pytest -q

# Run a single test file / test
uv run pytest tests/test_output.py
uv run pytest tests/test_output.py::test_aggregate_mixed_failed_is_partial_batch

# With coverage (terminal report with missing lines)
uv run pytest --cov --cov-report=term-missing
```

Without `uv` (activated virtual environment):

```bash
pytest -q
```

The opt-in live smoke test (real login + quota) is marked `live` and gated behind `O2CLOUD_LIVE=1`;
it is skipped by default and never runs in CI.

## Test organization

- All tests live in the top-level `tests/` directory.
- File naming: `test_<module>.py` (e.g. `test_output.py`, `test_errors.py`, `test_config.py`,
  `test_secrets.py`, `test_cli.py`).
- Tests that need isolated config/state set `O2CLOUD_CONFIG_DIR` / `O2CLOUD_STATE_DIR` to a
  `tmp_path` (see `tests/conftest.py`).
- Keyring is mocked in-memory (see `tests/conftest.py`) so no OS keychain is touched.
- The **browser login** (`tests/test_browser_login.py`) uses a **fake session** and fake clock — no
  real Chromium/Playwright runs in CI. The real end-to-end login (which needs a human for the SMS
  step) is a manual verification, not a CI test.

## Writing tests

- Prefer testing the **pure functions** in `output.py` (envelope builders, exit-code aggregation)
  directly — they are decoupled from Typer.
- For CLI behaviour, use `CliRunner().invoke(app, [...])` and assert `result.exit_code` and the
  parsed JSON on stdout.
- Never write real secrets in tests; use the in-memory keyring fixture and `monkeypatch`.

## The full gate

```bash
uv run ruff check .     # lint
uv run ruff format --check .
uv run mypy src         # static typing
uv run pytest -q        # tests
```

## Coverage

The suite aims for meaningful coverage of the infrastructure, the output contract, the CLI surface,
and the SAPI client. Endpoints that are still best-effort (for example `search` and `share`, pending
further capture) are covered as far as the observed behaviour allows.
