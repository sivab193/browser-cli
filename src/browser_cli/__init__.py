"""browser-cli: a fast web-browsing agent driven by the Bivia decision model.

Any LLM or coding agent can invoke the `browser-cli` command to drive a real
browser toward a natural-language goal. Bivia decides which operation and which
element to act on; a text model (optional) only writes text when typing.
"""

from .agent import Agent, AgentState
from .bivia import BiviaClient, BiviaError

__all__ = ["Agent", "AgentState", "BiviaClient", "BiviaError"]
__version__ = "0.1.0"
