"""Example chain plugin: merge multi-source context into the user message.

Subscribes to agent/pre-llm-call (observe class). Every source contributes
{"context": str}; the bridge concatenates them in registration order and the
host injects the merged text into the user message (never the system prompt,
preserving prompt-cache prefix).
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List

from .. import protocol


class ContextInjector:
    name = "context_injector"
    events: List[str] = [protocol.EVENT_PRE_LLM_CALL]

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        # Example source: environment marker. Real chains pull from memory,
        # cwd files, or any other context source.
        marker = os.environ.get("HERMES_EVENT_BRIDGE_CONTEXT", "")
        if marker:
            return protocol.context_injection(f"[event-bridge] {marker}")
        return None


plugin = ContextInjector()
