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

## Releasing

Releases are published to PyPI automatically by the `Publish to PyPI` workflow
(`.github/workflows/publish.yml`) whenever a GitHub Release is published. It uses PyPI
**Trusted Publishing** (OpenID Connect), so no PyPI API tokens are stored in the repository.

### One-time setup (PyPI side)

Because the project does not exist on PyPI yet, register a **pending publisher** first:

1. Sign in to PyPI → <https://pypi.org/manage/account/publishing/> → *Add a pending publisher*.
2. Fill in:
   - **PyPI Project Name:** `o2cloud`
   - **Owner:** `dbaratech`
   - **Repository name:** `o2cloud`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`
3. (Recommended) In GitHub → *Settings → Environments*, create an environment named `pypi` and add
   required reviewers so a release must be approved before it publishes.

After the first successful publish, the pending publisher becomes a regular trusted publisher.

### Cutting a release

1. Bump the version in `pyproject.toml`, `src/o2cloud/__init__.py`, and the `user_agent` default in
   `src/o2cloud/config.py` (all must match; the workflow fails if `pyproject.toml` and the tag differ).
2. Add a `CHANGELOG.md` entry, commit, and open a PR / merge to `main`.
3. Create a GitHub Release with a tag `vX.Y.Z` (matching the new version).
4. The workflow runs the gate, builds the sdist + wheel, and publishes to PyPI.

## Reporting bugs and requesting features

Open an issue with a clear description, the command you ran, the expected versus actual behaviour, and
relevant environment details (OS, Python version, `o2cloud --version`). Never paste real cookies,
tokens, or other credentials into an issue.
