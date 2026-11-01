"""The agent loop: observe -> decide (Bivia) -> act -> verify.

Design mirrors jev-ultrafast's indexed action space, but the policy is the Bivia
decision model instead of a single speculative model call:

  1. Snapshot the page into a numbered element table.
  2. Ask Bivia /boolean whether the goal is already satisfied (DONE check).
  3. Ask Bivia /choice which operation to perform next.
  4. Ask Bivia /choice which element to act on (targets filtered by operation).
  5. If TYPE_TEXT, an optional text model writes the string; otherwise execute.

Every decision is one bounded, calibrated call. The executor re-resolves the
chosen element from the live DOM and verifies the action before trusting it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from .bivia import BiviaClient
from .browser import Browser
from .text_helper import TextHelper

OPERATIONS = ["CLICK", "TYPE_TEXT", "SELECT", "SCROLL_DOWN", "SCROLL_UP", "DONE", "BLOCKED"]


@dataclass
class AgentState:
    """One step of the run, yielded to the caller."""

    step: int
    status: str  # running | done | blocked | failed
    operation: str | None
    target_index: int | None
    target_name: str | None
    text: str | None
    elapsed_ms: int
    url: str
    note: str = ""
    distribution: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "operation": self.operation,
            "target_index": self.target_index,
            "target_name": self.target_name,
            "text": self.text,
            "elapsed_ms": self.elapsed_ms,
            "url": self.url,
            "note": self.note,
            "distribution": self.distribution,
        }


class Agent:
    """Drives a browser toward a natural-language goal using Bivia as the policy."""

    def __init__(
        self,
        url: str,
        goal: str,
        *,
        bivia: BiviaClient | None = None,
        browser: Browser | None = None,
        text_helper: TextHelper | None = None,
        max_steps: int = 25,
        mode: str = "fast",
        headless: bool = False,
        user_data_dir: str | None = None,
    ) -> None:
        self.url = url
        self.goal = goal
        self.max_steps = max_steps
        self.mode = mode
        self._owns_browser = browser is None
        self._owns_bivia = bivia is None
        self.browser = browser or Browser(headless=headless, user_data_dir=user_data_dir)
        self.bivia = bivia or BiviaClient(mode=mode)
        self.text_helper = text_helper or TextHelper()
        self._start = 0.0

    def __enter__(self) -> Agent:
        self.browser.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._owns_browser:
            self.browser.close()
        if self._owns_bivia:
            self.bivia.close()

    # --- Loop ---------------------------------------------------------------

    def run(self) -> Iterator[AgentState]:
        self._start = monotonic()
        self.browser.goto(self.url)

        for step in range(1, self.max_steps + 1):
            snap = self.browser.snapshot()
            elements = snap["elements"]
            state_text = self._state_text(snap)

            # 1. DONE check first — independent verification of the outcome.
            done = self.bivia.boolean(
                state=state_text,
                question=f"Has this goal been fully accomplished on the current page? Goal: {self.goal}",
            )
            if done.answered and done.value in (True, "yes", "true"):
                yield self._state(step, "done", "DONE", None, None, None,
                                  note="Goal satisfied", dist=done.distribution)
                return

            # 2. Choose an operation.
            op_choices = self._available_operations(elements, snap)
            op = self.bivia.choice(
                state=state_text,
                question=f"What is the single best next browser action toward the goal? Goal: {self.goal}",
                choices=op_choices,
            )
            operation = op.value if op.answered else None
            if operation == "BLOCKED" or operation is None:
                yield self._state(step, "blocked", "BLOCKED", None, None, None,
                                  note=op.abstain_reason or "No confident operation",
                                  dist=op.distribution)
                return
            if operation == "DONE":
                yield self._state(step, "done", "DONE", None, None, None,
                                  note="Policy chose DONE", dist=op.distribution)
                return

            # Scrolling needs no target.
            if operation in ("SCROLL_DOWN", "SCROLL_UP"):
                ok = self.browser.scroll("down" if operation == "SCROLL_DOWN" else "up")
                yield self._state(step, "running" if ok else "failed", operation, None, None, None,
                                  note="scrolled" if ok else "scroll failed", dist=op.distribution)
                if not ok:
                    return
                continue

            # 3. Choose a target element compatible with the operation.
            targets = self._targets_for(operation, elements)
            if not targets:
                yield self._state(step, "running", operation, None, None, None,
                                  note="No compatible target; scrolling to look further")
                self.browser.scroll("down")
                continue

            labels = [self._label(e) for e in targets]
            tgt = self.bivia.choice(
                state=state_text,
                question=(
                    f"Which element should receive a {operation} to progress the goal? "
                    f"Goal: {self.goal}"
                ),
                choices=labels,
            )
            if not tgt.answered:
                yield self._state(step, "blocked", operation, None, None, None,
                                  note=tgt.abstain_reason or "No confident target",
                                  dist=tgt.distribution)
                return
            chosen = targets[labels.index(tgt.value)] if tgt.value in labels else targets[0]

            # 4. Execute.
            yield from self._execute(step, operation, chosen, snap, tgt.distribution)

        yield self._state(self.max_steps, "failed", None, None, None, None,
                          note="Reached max steps without completing the goal")

    # --- Execution helpers --------------------------------------------------

    def _execute(
        self, step: int, operation: str, element: dict, snap: dict, dist: dict
    ) -> Iterator[AgentState]:
        ref = element["ref"]
        name = element.get("name") or element.get("value") or element["role"]

        if operation == "CLICK":
            ok = self.browser.click(ref)
            yield self._state(step, "running" if ok else "failed", "CLICK",
                              element["index"], name, None,
                              note="clicked" if ok else "click failed", dist=dist)

        elif operation == "TYPE_TEXT":
            text = self.text_helper.generate(
                goal=self.goal,
                field_name=element.get("name", ""),
                field_value=element.get("value", ""),
                page_title=snap.get("title", ""),
            )
            ok = self.browser.type_text(ref, text)
            yield self._state(step, "running" if ok else "failed", "TYPE_TEXT",
                              element["index"], name, text,
                              note="typed" if ok else "type failed", dist=dist)

        elif operation == "SELECT":
            option = self._choose_option(element, snap)
            ok = self.browser.select(ref, option) if option is not None else False
            yield self._state(step, "running" if ok else "failed", "SELECT",
                              element["index"], name, option,
                              note=f"selected {option!r}" if ok else "select failed", dist=dist)
        else:
            yield self._state(step, "failed", operation, element["index"], name, None,
                              note="unknown operation")

    def _choose_option(self, element: dict, snap: dict) -> str | None:
        options = element.get("options") or []
        if not options:
            return None
        labels = [o["label"] for o in options if o["label"]]
        if not labels:
            return None
        dec = self.bivia.choice(
            state=self._state_text(snap),
            question=f"Which option fits the goal? Goal: {self.goal}",
            choices=labels,
        )
        return dec.value if dec.answered and dec.value in labels else labels[0]

    # --- Policy inputs ------------------------------------------------------

    def _available_operations(self, elements: list[dict], snap: dict) -> list[str]:
        ops = {"DONE", "BLOCKED"}
        if any(e["role"] in ("button", "link", "checkbox", "radio", "tab", "menuitem", "option")
               or e["tag"] in ("a", "button") for e in elements):
            ops.add("CLICK")
        if any(e.get("editable") for e in elements):
            ops.add("TYPE_TEXT")
        if any(e["tag"] == "select" and e.get("options") for e in elements):
            ops.add("SELECT")
        scroll = snap.get("scroll", {})
        if scroll.get("y", 0) + scroll.get("vh", 0) < scroll.get("maxY", 0):
            ops.add("SCROLL_DOWN")
        if scroll.get("y", 0) > 0:
            ops.add("SCROLL_UP")
        # Keep a stable order for calibrated distributions.
        return [o for o in OPERATIONS if o in ops]

    def _targets_for(self, operation: str, elements: list[dict]) -> list[dict]:
        if operation == "CLICK":
            return [e for e in elements
                    if e["role"] in ("button", "link", "checkbox", "radio", "tab",
                                      "menuitem", "option")
                    or e["tag"] in ("a", "button")
                    or (e["tag"] == "input" and e["role"] == "button")]
        if operation == "TYPE_TEXT":
            return [e for e in elements if e.get("editable") and e["tag"] != "select"]
        if operation == "SELECT":
            return [e for e in elements if e["tag"] == "select" and e.get("options")]
        return []

    def _label(self, e: dict) -> str:
        val = f" = {e['value']}" if e.get("value") else ""
        return f"[{e['index']}] {e['role']}: {e['name']}{val}".strip()

    def _state_text(self, snap: dict) -> str:
        lines = [
            f"URL: {snap.get('url', '')}",
            f"Title: {snap.get('title', '')}",
            "",
            "Interactable elements:",
        ]
        for e in snap["elements"][:60]:
            lines.append(self._label(e))
        page_text = snap.get("text", "")
        if page_text:
            lines.append("")
            lines.append("Visible page text (excerpt):")
            lines.append(page_text[:1500])
        return "\n".join(lines)

    def _state(
        self, step, status, operation, idx, name, text, note="", dist=None
    ) -> AgentState:
        return AgentState(
            step=step,
            status=status,
            operation=operation,
            target_index=idx,
            target_name=name,
            text=text,
            elapsed_ms=int((monotonic() - self._start) * 1000),
            url=self.browser.page.url if self.browser.page else self.url,
            note=note,
            distribution=dist or {},
        )
