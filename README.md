# browser-cli

A fast web-browsing agent you run from the command line. Give it one URL and one
natural-language goal; it drives a real browser to accomplish it.

The policy is the [**Bivia** decision model](https://docs.articul8.ai/bivia/)
rather than a large language model. This mirrors
[`browser-use/jev-ultrafast`](https://github.com/browser-use/jev-ultrafast)'s
indexed action space, but swaps the single speculative model call for Bivia's
bounded, calibrated decisions:

> **LLMs generate. Bivia decides.** Use an LLM to write and plan, and Bivia for
> the bounded decisions around it.

`browser-cli` is built so **any coding agent or LLM can call it as a tool** —
pass `--json` and it emits machine-readable NDJSON with a predictable exit code.

## How it works

Each step is one observe → decide → act → verify cycle:

1. **Snapshot** the page into a numbered table of interactable controls
   (`snapshot.js`).
2. **DONE check** — `POST /boolean`: is the goal already satisfied?
3. **Operation** — `POST /choice`: `CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_DOWN`,
   `SCROLL_UP`, `DONE`, or `BLOCKED`. Only operations the page supports are offered.
4. **Target** — `POST /choice`: which element, from the ones compatible with the
   chosen operation.
5. **Text** — only when the operation is `TYPE_TEXT`, a small (optional) text
   model writes the exact string. Everything else is decided by Bivia.

Each decision is one calibrated call; Bivia can **abstain** instead of guessing,
which the agent surfaces as `BLOCKED`. The executor re-resolves the chosen
element from the live DOM and verifies the action before trusting it.

## Install

```bash
# zero-install, per invocation (best for agents / one-off runs)
uvx --from bivia-browser-cli browser-cli run -u https://example.com -g "find pricing"

# or install it
pip install bivia-browser-cli          # into the current environment
uv tool install bivia-browser-cli      # as a standalone tool
```

The package name on PyPI is `bivia-browser-cli`; the command it installs is
`browser-cli`. The Chromium browser the agent drives (~180MB) is **downloaded
automatically on first use** into a per-user cache
(`~/Library/Caches/browser-cli` on macOS, `~/.cache/browser-cli` on Linux), so
it survives across ephemeral `uvx` runs. To pre-warm it (e.g. before going
offline):

```bash
browser-cli install
```

Set your keys:

```bash
export A8_API_KEY="your-bivia-key"            # required — the decision policy

# optional: a small text model for TYPE_TEXT (OpenAI-compatible endpoint)
export TEXT_MODEL_API_KEY="your-openrouter-key"
export TEXT_MODEL="openai/gpt-4o-mini"        # any small model
export TEXT_MODEL_BASE_URL="https://openrouter.ai/api/v1"
```

Without a text model, `TYPE_TEXT` falls back to typing the goal text — fine for
search boxes. Check your setup:

```bash
browser-cli doctor
```

## Use

```bash
# Human-readable, visible browser
browser-cli run \
  --url https://en.wikipedia.org/wiki/Main_Page \
  --goal "Open the article about Gödel's incompleteness theorems"

# Headless + deep mode for harder pages
browser-cli run -u https://example.com -g "find the pricing page" --headless --mode deep
```

### As a tool for another agent

```bash
browser-cli run --url https://example.com --goal "accept cookies and go to docs" --json --headless
```

Output is NDJSON — one object per step, then a final result object:

```json
{"step": 1, "status": "running", "operation": "CLICK", "target_index": 4, "target_name": "Accept all", "elapsed_ms": 820, "url": "https://example.com", "note": "clicked", "distribution": {}}
{"result": "done", "goal": "...", "url": "https://example.com/docs", "steps": 3, "elapsed_ms": 2140, "note": "Goal satisfied"}
```

Exit codes let a caller branch without parsing:

| code | meaning |
|------|---------|
| `0`  | goal done |
| `1`  | blocked (Bivia abstained / no confident action) |
| `2`  | failed or error |

### As a Python library

```python
from browser_cli import Agent

with Agent("https://example.com", "find the pricing page", headless=True) as agent:
    for state in agent.run():
        print(state.elapsed_ms, state.status, state.operation, state.target_name)
```

## Options

| flag | meaning |
|------|---------|
| `--url, -u`      | starting URL (required) |
| `--goal, -g`     | natural-language goal (required) |
| `--json`         | emit NDJSON for machine consumption |
| `--headless`     | run without a visible window |
| `--mode`         | `fast` (default) or `deep` |
| `--max-steps`    | decision-step cap (default 25) |
| `--profile`      | persistent browser profile dir (reuse logins) |
| `--quiet, -q`    | suppress the live step view |

## Limits

Common HTML and ARIA controls are supported, not the full accessible-name spec.
Shadow roots, frames, canvas, uploads, pop-up tabs, nested scrolling, and
arbitrary keyboard widgets are out of scope for this MVP. A `DONE` result is
Bivia's judgment — verify important outcomes independently.

## Development & publishing

```bash
pip install -e ".[dev]"      # editable install with dev tools
ruff check src/              # lint
python -m build              # build wheel + sdist into dist/
twine check dist/*           # validate metadata

# publish: test first, then real PyPI
twine upload --repository testpypi dist/*
twine upload dist/*
```

One upload to PyPI serves `pip`, `pipx`, `uv tool install`, and `uvx` alike.

## Credits

Action-space design inspired by
[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast).
Decision policy powered by [Bivia](https://docs.articul8.ai/bivia/).
