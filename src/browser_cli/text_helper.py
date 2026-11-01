"""Optional text generation for the TYPE_TEXT operation.

Following the jev-ultrafast split: Bivia *decides* (which element, which
operation), and an LLM only *generates* the small string to type. If no text
model is configured, the agent derives the text heuristically from the goal.

The helper talks to any OpenAI-compatible chat-completions endpoint. Configure:
  TEXT_MODEL_API_KEY   - API key (e.g. an OpenRouter key)
  TEXT_MODEL_BASE_URL  - default https://openrouter.ai/api/v1
  TEXT_MODEL           - default a small, fast model
Model output must parse as a tiny JSON object {"text": "..."} before it is typed.
"""

from __future__ import annotations

import json
import os

import httpx

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-4o-mini"

_SYSTEM = (
    "You write the exact text to type into one web form field. "
    'Respond ONLY with a compact JSON object: {"text": "<value>"}. '
    "No prose, no markdown, no explanation. The value is what a user would type "
    "into the described field to make progress on the goal."
)


class TextHelper:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("TEXT_MODEL_API_KEY")
        self.base_url = (
            base_url or os.environ.get("TEXT_MODEL_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.environ.get("TEXT_MODEL") or DEFAULT_MODEL
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def generate(self, goal: str, field_name: str, field_value: str, page_title: str) -> str:
        """Return the text to type. Falls back to a heuristic if no model is set."""
        if not self.enabled:
            return self._heuristic(goal, field_name)

        prompt = (
            f"Goal: {goal}\n"
            f"Page: {page_title}\n"
            f"Field name/label: {field_name!r}\n"
            f"Current field value: {field_value!r}\n"
            "What text should be typed into this field?"
        )
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            return self._parse(content) or self._heuristic(goal, field_name)
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            return self._heuristic(goal, field_name)

    @staticmethod
    def _parse(content: str) -> str | None:
        # Strip code fences if present.
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            obj = json.loads(content)
            text = obj.get("text")
            if isinstance(text, str):
                return text
        except ValueError:
            pass
        return None

    @staticmethod
    def _heuristic(goal: str, field_name: str) -> str:
        """Without a model, just type the goal text. Good enough for search boxes."""
        return goal.strip()
