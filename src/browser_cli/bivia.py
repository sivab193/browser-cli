"""Thin client for the Bivia decision API (https://docs.articul8.ai/bivia/).

Bivia answers bounded decisions in one pass and returns a typed, calibrated
result. We use it as the agent policy: pick an operation, pick a target element,
and decide whether the goal is done.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.articul8.ai/bivia"

# Shared config written by the official Bivia CLI (`bivia key` / `bivia install`).
BIVIA_CONFIG_PATH = Path.home() / ".bivia" / "config"


class BiviaError(RuntimeError):
    """Raised when the Bivia API returns an error or an unusable response."""


def _read_config_value(key: str, path: Path = BIVIA_CONFIG_PATH) -> str | None:
    """Read KEY=value from the Bivia CLI's env-style config file, if present."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            # Strip surrounding quotes and whitespace.
            return value.strip().strip("'\"") or None
    return None


def resolve_api_key(api_key: str | None = None) -> str | None:
    """Find the Bivia API key, in priority order.

    1. Explicit argument (e.g. --api-key).
    2. A8_API_KEY environment variable (browser-cli convention).
    3. BIVIA_API_KEY environment variable (Bivia CLI convention).
    4. ~/.bivia/config written by the official Bivia CLI (BIVIA_API_KEY=...).
    """
    if api_key:
        return api_key
    for env in ("A8_API_KEY", "BIVIA_API_KEY"):
        value = os.environ.get(env)
        if value:
            return value
    return _read_config_value("BIVIA_API_KEY")


@dataclass
class Decision:
    """Normalized view of a Bivia response."""

    type: str
    value: Any
    status: str
    probability: float | None = None
    distribution: dict[str, float] = field(default_factory=dict)
    abstain_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def answered(self) -> bool:
        return self.status == "answered" and self.value is not None

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> Decision:
        return cls(
            type=data.get("type", ""),
            value=data.get("value"),
            status=data.get("status", "answered"),
            probability=data.get("probability"),
            distribution=data.get("distribution") or {},
            abstain_reason=data.get("abstain_reason"),
            raw=data,
        )


def api_key_source(api_key: str | None = None) -> str | None:
    """Describe where the resolved key comes from, for diagnostics. None if absent."""
    if api_key:
        return "explicit argument"
    for env in ("A8_API_KEY", "BIVIA_API_KEY"):
        if os.environ.get(env):
            return f"{env} environment variable"
    if _read_config_value("BIVIA_API_KEY"):
        return str(BIVIA_CONFIG_PATH)
    return None


class BiviaClient:
    """Synchronous Bivia client covering the decision endpoints used by the agent."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        mode: str = "fast",
        timeout: float = 30.0,
    ) -> None:
        self.api_key = resolve_api_key(api_key)
        if not self.api_key:
            raise BiviaError(
                "No Bivia API key. Set up the Bivia CLI (key saved to ~/.bivia/config), "
                "or set A8_API_KEY / BIVIA_API_KEY, or pass api_key."
            )
        self.base_url = (base_url or os.environ.get("A8_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.mode = mode
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BiviaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(self, path: str, payload: dict[str, Any]) -> Decision:
        payload.setdefault("mode", self.mode)
        try:
            resp = self._client.post(f"{self.base_url}/{path.lstrip('/')}", json=payload)
        except httpx.HTTPError as exc:  # network / timeout
            raise BiviaError(f"Bivia request to /{path} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise BiviaError(
                f"Bivia /{path} returned HTTP {resp.status_code}: {resp.text[:500]}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise BiviaError(f"Bivia /{path} returned non-JSON: {resp.text[:200]}") from exc
        return Decision.from_response(data)

    # --- Decision endpoints -------------------------------------------------

    def choice(
        self,
        state: str,
        question: str,
        choices: list[str],
        *,
        allow_abstain: bool = True,
        mode: str | None = None,
    ) -> Decision:
        """Pick one option from a list."""
        payload: dict[str, Any] = {
            "state": state,
            "question": question,
            "choices": choices,
            "allow_abstain": allow_abstain,
        }
        if mode:
            payload["mode"] = mode
        return self._post("choice", payload)

    def boolean(
        self,
        state: str,
        question: str,
        *,
        allow_abstain: bool = True,
        mode: str | None = None,
    ) -> Decision:
        """Yes / no decision."""
        payload: dict[str, Any] = {
            "state": state,
            "question": question,
            "allow_abstain": allow_abstain,
        }
        if mode:
            payload["mode"] = mode
        return self._post("boolean", payload)

    def score(
        self,
        state: str,
        question: str,
        *,
        value_range: tuple[float, float] = (0.0, 1.0),
        buckets: int = 11,
        mode: str | None = None,
    ) -> Decision:
        """Rate on a numeric scale."""
        payload: dict[str, Any] = {
            "state": state,
            "question": question,
            "range": list(value_range),
            "buckets": buckets,
        }
        if mode:
            payload["mode"] = mode
        return self._post("score", payload)
