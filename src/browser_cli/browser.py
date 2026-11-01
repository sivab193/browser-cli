"""Browser connection and action execution via Playwright.

Keeps the DOM-snapshot and execution concerns separate from the decision loop.
Every executed target is re-resolved from a live node (tagged by snapshot.js with
a data-bcli-ref attribute) and re-checked for freshness/occlusion before acting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    Page,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeout,
)

from .bootstrap import ensure_browsers_path, install_chromium, looks_like_missing_browser

_SNAPSHOT_JS = (Path(__file__).parent / "snapshot.js").read_text(encoding="utf-8")


class Browser:
    """A single-page browser session."""

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: str | None = None,
        auto_install: bool = True,
    ) -> None:
        self._headless = headless
        self._user_data_dir = user_data_dir
        self._auto_install = auto_install
        self._pw = None
        self._context = None
        self._browser = None
        self._started = False
        self.page: Page | None = None

    def start(self) -> None:
        if self._started:
            return
        ensure_browsers_path()
        self._pw = sync_playwright().start()
        try:
            self._launch()
        except PlaywrightError as exc:
            # Chromium not installed yet — bootstrap it once, then retry.
            if self._auto_install and looks_like_missing_browser(str(exc)):
                if not install_chromium():
                    self._pw.stop()
                    self._pw = None
                    raise
                self._launch()
            else:
                self._pw.stop()
                self._pw = None
                raise
        self._started = True

    def _launch(self) -> None:
        assert self._pw is not None
        if self._user_data_dir:
            # Persistent context: reuse an existing profile (cookies, logins).
            self._context = self._pw.chromium.launch_persistent_context(
                self._user_data_dir, headless=self._headless
            )
            self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        else:
            self._browser = self._pw.chromium.launch(headless=self._headless)
            self._context = self._browser.new_context()
            self.page = self._context.new_page()

    def close(self) -> None:
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def __enter__(self) -> Browser:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- Navigation & observation ------------------------------------------

    def goto(self, url: str) -> None:
        assert self.page is not None
        self.page.goto(url, wait_until="domcontentloaded")

    def snapshot(self) -> dict[str, Any]:
        """Return an indexed table of visible, interactable controls + page text."""
        assert self.page is not None
        return self.page.evaluate(_SNAPSHOT_JS)

    # --- Execution ----------------------------------------------------------

    def _locator(self, ref: str):
        assert self.page is not None
        return self.page.locator(f"[data-bcli-ref='{ref}']")

    def click(self, ref: str) -> bool:
        loc = self._locator(ref)
        try:
            loc.scroll_into_view_if_needed(timeout=2000)
            loc.click(timeout=4000)
            self._settle()
            return True
        except (PlaywrightTimeout, PlaywrightError):
            return False

    def type_text(self, ref: str, text: str) -> bool:
        loc = self._locator(ref)
        try:
            loc.scroll_into_view_if_needed(timeout=2000)
            loc.click(timeout=4000)
            loc.fill("", timeout=2000)
            loc.type(text, delay=10, timeout=5000)
            # After typing into a combobox-like control, wait briefly for suggestions.
            self._settle(cap_ms=200)
            return True
        except (PlaywrightTimeout, PlaywrightError):
            return False

    def select(self, ref: str, option_label: str) -> bool:
        loc = self._locator(ref)
        try:
            loc.select_option(label=option_label, timeout=3000)
            self._settle()
            return True
        except (PlaywrightTimeout, PlaywrightError):
            # Fall back to matching by value.
            try:
                loc.select_option(value=option_label, timeout=3000)
                self._settle()
                return True
            except (PlaywrightTimeout, PlaywrightError):
                return False

    def scroll(self, direction: str) -> bool:
        assert self.page is not None
        dy = self.page.viewport_size["height"] * 0.8 if self.page.viewport_size else 600
        if direction == "up":
            dy = -dy
        try:
            self.page.mouse.wheel(0, dy)
            self._settle(cap_ms=100)
            return True
        except PlaywrightError:
            return False

    def _settle(self, cap_ms: int = 400) -> None:
        """Short, bounded wait for the page to stabilize after an action."""
        assert self.page is not None
        try:
            self.page.wait_for_load_state("networkidle", timeout=cap_ms)
        except PlaywrightTimeout:
            pass
        self.page.wait_for_timeout(min(cap_ms, 100))
