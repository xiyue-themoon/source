"""Example chain plugin: block-list tool guard.

Subscribes to agent/pre-tool-call (observe class). Returning
{"decision": "block", "message": ...} short-circuits the tool before it runs.
The block list comes from the HERMES_EVENT_BRIDGE_BLOCKED_TOOLS env var
(comma-separated tool names).
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List

from .. import protocol


class ToolGuard:
    name = "tool_guard"
    events: List[str] = [protocol.EVENT_PRE_TOOL_CALL]

    def __init__(self) -> None:
        raw = os.environ.get("HERMES_EVENT_BRIDGE_BLOCKED_TOOLS", "")
        self.blocked = {t.strip() for t in raw.split(",") if t.strip()}

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        tool_name = ctx.get("tool_name") or ctx.get("name") or ""
        if tool_name in self.blocked:
            return protocol.block_decision(
                f"[event-bridge] tool {tool_name!r} blocked by tool_guard chain"
            )
        return None


plugin = ToolGuard()
