# Contributing

Thanks for your interest in improving `browser-cli`.

## Development setup

```bash
git clone https://github.com/sivab193/browser-cli.git
cd browser-cli
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
browser-cli install        # download Chromium once
```

## Project layout

```
src/browser_cli/
  cli.py          Typer CLI: run / install / doctor
  agent.py        The observe -> decide -> act -> verify loop
  bivia.py        Bivia decision API client (choice / boolean / score)
  browser.py      Playwright browser connection + action execution
  bootstrap.py    On-demand Chromium install into a persistent cache
  text_helper.py  Optional text model for the TYPE_TEXT operation
  snapshot.js     Atomic DOM snapshot -> indexed element table
```

The two halves to keep separate: **policy** (Bivia decides which operation and
element) and **actuation** (Playwright executes and verifies). `agent.py` is the
only place they meet.

## Before you open a PR

```bash
ruff check src/            # lint must pass
python -m build            # package must build
twine check dist/*         # metadata must validate
```

If you add a user-facing change, update `README.md`, `CHANGELOG.md`, and — when
the JSON contract or CLI flags change — `docs/AGENT_INTEGRATION.md`.

## Commit and PR style

- Keep commits focused; describe the behavior change, not the mechanics.
- Note anything you could not verify (e.g. live Bivia API calls need `A8_API_KEY`).

## Releasing

1. Bump `version` in `pyproject.toml` and add a `CHANGELOG.md` entry.
2. `python -m build && twine check dist/*`
3. `twine upload dist/*` (a published version can never be replaced — bump instead).
4. Tag the release: `git tag v<version> && git push --tags`.
