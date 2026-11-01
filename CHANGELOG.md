# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-11-01

### Changed
- The Bivia API key now defaults to the official Bivia CLI's credential file at
  `~/.bivia/config` (`BIVIA_API_KEY=...`). If the Bivia CLI is set up, no key env
  var is needed. Resolution order: `--api-key` → `A8_API_KEY` → `BIVIA_API_KEY`
  → `~/.bivia/config`.
- `browser-cli doctor` now reports where the key was found.

## [0.1.0] - 2026-11-01

Initial release.

### Added
- `browser-cli run` — drive a browser toward a natural-language goal. The policy
  is the [Bivia](https://docs.articul8.ai/bivia/) decision model (`/boolean` for
  the DONE check, `/choice` for operation and target selection), following the
  indexed action space of
  [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast).
- `--json` NDJSON output and `0/1/2` exit codes so any coding agent or LLM can
  call the tool and branch on the result without parsing text.
- `browser-cli install` and `browser-cli doctor` — Chromium is downloaded on
  demand into a persistent per-user cache, so `uvx` runs work without a separate
  install step.
- Optional text model (OpenAI-compatible) for the `TYPE_TEXT` operation; without
  one, typing falls back to the goal text.
- Python library API: `from browser_cli import Agent`.

### Known limits
- Common HTML and ARIA controls only — not the full accessible-name spec. Shadow
  roots, frames, canvas, uploads, pop-up tabs, nested scrolling, and arbitrary
  keyboard widgets are out of scope for this MVP.
- A `DONE` result is Bivia's judgment; verify important outcomes independently.

[0.1.1]: https://github.com/sivab193/browser-cli/releases/tag/v0.1.1
[0.1.0]: https://github.com/sivab193/browser-cli/releases/tag/v0.1.0
