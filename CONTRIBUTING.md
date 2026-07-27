# Contributing

Thanks for your interest in improving `o2cloud`. This document covers the development setup, the
quality gate, and how to propose changes.

## Development setup

The project targets **Python 3.11+** and is developed with [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/o2cloud/o2cloud
cd o2cloud
uv venv --python 3.11
uv pip install -e ".[dev]"     # editable install with dev tooling
uv run o2cloud --help
```

### Browser login extra

Browser-assisted login uses Playwright, which is an optional extra:

```bash
uv pip install -e ".[dev,browser]"
uv run playwright install chromium     # one-time Chromium download
```

## The quality gate

Every change must keep the following gate green. Run it locally before opening a pull request:

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run mypy src                # static typing (strict)
uv run pytest -q               # tests
```

`uv run ruff format .` applies formatting fixes in place. See [`docs/testing.md`](docs/testing.md) for
the full testing guide, including running individual tests and the opt-in live smoke test.

## Code style

- Formatting and linting are enforced by `ruff` (configured in `pyproject.toml`); do not hand-format
  around it.
- Type hints are required. `mypy` runs in strict mode over `src`.
- Match the existing patterns: the clean `CLI -> service -> api -> infrastructure` layering, typed
  errors mapped to the frozen exit-code table, and pydantic models for untrusted SAPI responses. See
  [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
- Never commit secrets. Credentials live only in the OS keyring or `O2CLOUD_*` environment variables,
  never in files, logs, or tests.

## Working with the reverse-engineered API

There is no official O2 Cloud API. New endpoints must be grounded in real observed traffic and
documented in [`docs/api-reference.md`](docs/api-reference.md) — do not invent paths or fields. When
you add or correct an endpoint, update that reference in the same change.

## Pull requests

- Keep pull requests focused and reasonably small; one logical change per PR.
- Include tests for new behaviour and keep the gate green.
- Update the relevant documentation (`README.md`, `docs/*`) when behaviour changes.
- Add a `CHANGELOG.md` entry under a new or existing unreleased version heading.
- Write clear commit messages describing the intent of the change.

## Reporting bugs and requesting features

Open an issue with a clear description, the command you ran, the expected versus actual behaviour, and
relevant environment details (OS, Python version, `o2cloud --version`). Never paste real cookies,
tokens, or other credentials into an issue.
