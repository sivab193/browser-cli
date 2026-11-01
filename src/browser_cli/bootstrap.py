"""Chromium bootstrap for Playwright.

`pip install` / `uvx` pull in the Playwright *library* but not the Chromium
binary it drives. For a zero-install experience (especially under `uvx`, whose
environment is ephemeral), we detect a missing browser and install it on demand.

Resolution order for where the browser lives:
  1. PLAYWRIGHT_BROWSERS_PATH, if the user set it (shared, persists across uvx runs).
  2. Otherwise a stable per-user cache dir we set ourselves, so an ephemeral uvx
     run can still find a browser installed by a previous run.
Playwright's own default (0 = alongside the package) is avoided because an
ephemeral uvx package dir is discarded after the command.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SENTINEL_MISSING = (
    "executable doesn't exist",
    "looks like playwright",
    "please run the following command",
    "browsertype.launch",
)


def browsers_path() -> Path:
    """Stable location for Playwright browsers; also exported to the environment."""
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env not in ("0",):
        path = Path(env).expanduser()
    else:
        # Per-user cache that survives across ephemeral uvx invocations.
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Caches"
        elif sys.platform.startswith("win"):
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        else:
            base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        path = base / "browser-cli" / "ms-playwright"
    # Make sure every child process (and Playwright itself) agrees on the path.
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
    return path


def looks_like_missing_browser(message: str) -> bool:
    msg = message.lower()
    return any(s in msg for s in _SENTINEL_MISSING)


def ensure_browsers_path() -> None:
    """Export PLAYWRIGHT_BROWSERS_PATH before Playwright starts."""
    browsers_path()


def install_chromium(*, with_deps: bool = False, quiet: bool = False) -> bool:
    """Run `playwright install chromium` into our browsers path. Returns success."""
    browsers_path()  # ensure env var is set for the child process
    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    if with_deps and not sys.platform.startswith("win"):
        # --with-deps needs root on Linux; skip silently if it fails.
        cmd.append("--with-deps")
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=quiet,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0
