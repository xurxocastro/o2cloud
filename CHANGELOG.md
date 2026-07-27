# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-07-27

### Added

- `ls` and `tree` now resolve file names and sizes. The sparse SAPI media listing is enriched with a
  batch detail call, so listings show human-readable names instead of bare ids. A failing detail call
  is best-effort: affected files fall back to their id rather than failing the whole listing.
- `--no-detail` flag on `ls`/`tree` to keep the fast, raw, id-only listing.
- Agent usage guide ([`docs/agent-usage.md`](docs/agent-usage.md)) documenting the JSON envelope and
  exit-code contract, the environment-variable authentication pattern
  (`O2CLOUD_COOKIE` / `O2CLOUD_TOKEN`) and its human-in-the-loop renewal, an invocation example, and
  common gotchas.

## [0.3.0] - 2026-07-23

### Added

- Browser-assisted login: `o2cloud login` now opens a real browser (Playwright, via the optional
  `browser` extra). The user completes MobileConnect/SMS, and the CLI harvests the session cookies —
  including the httpOnly `JSESSIONID` — removing the need for the manual DevTools "Copy as cURL" step.
- APK analysis notes ([`docs/apk-analysis.md`](docs/apk-analysis.md)) documenting why a fully silent
  OAuth refresh is not feasible (a runtime-fetched client secret and SIM-based MobileConnect), which
  is the rationale for choosing browser automation.

### Changed

- `--import-cookie` remains available as the fallback that needs no Playwright. New `--timeout` and
  `--headless` flags on `login`.

## [0.2.0] - 2026-07-22

### Added

- Initial functional release: a scriptable, agent-friendly CLI for O2 Cloud over the reverse-engineered
  Funambol SAPI. Commands: `login`, `logout`, `whoami`, `account`, `quota`, `ls`, `tree`, `stat`,
  `upload`, `download`, `mkdir`, `mv`, `cp`, `rm`, `search`, `sync`, `share`, `trash`, and `config`.
- `--json` output mode with a frozen exit-code contract for reliable scripting and agent use.
- Verified end-to-end against a live account, including a byte-exact upload/download cycle.

### Security

- Pre-release security review. Fixed a token leak into the error envelope and a path-traversal risk in
  download filename handling.

[0.4.0]: https://github.com/o2cloud/o2cloud/releases/tag/v0.4.0
[0.3.0]: https://github.com/o2cloud/o2cloud/releases/tag/v0.3.0
[0.2.0]: https://github.com/o2cloud/o2cloud/releases/tag/v0.2.0
