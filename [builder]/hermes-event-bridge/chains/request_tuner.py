"""Example chain plugin: tune LLM request parameters.

Subscribes to agent/request (request class, waterfall). Returns
{"request": {...}} to replace the provider kwargs sent to the LLM. The
bridge forwards the modified request through later chains and finally to
the host, which applies it before the API call.

Tunables via env vars (useful for verification matrix item 2):
  HERMES_EVENT_BRIDGE_MAX_TOKENS  - override max_tokens (int)
  HERMES_EVENT_BRIDGE_MODEL       - override model (str)
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List

from .. import protocol


class RequestTuner:
    name = "request_tuner"
    events: List[str] = [protocol.EVENT_REQUEST]

    def __init__(self) -> None:
        raw_max = os.environ.get("HERMES_EVENT_BRIDGE_MAX_TOKENS", "")
        self.max_tokens = int(raw_max) if raw_max.isdigit() else None
        self.model = os.environ.get("HERMES_EVENT_BRIDGE_MODEL", "") or None

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        request = ctx.get("request")
        if not isinstance(request, dict):
            return None
        changed = dict(request)
        mutated = False
        if self.max_tokens is not None and changed.get("max_tokens") != self.max_tokens:
            changed["max_tokens"] = self.max_tokens
            mutated = True
        if self.model is not None and changed.get("model") != self.model:
            changed["model"] = self.model
            mutated = True
        if not mutated:
            return None
        return protocol.request_replacement(changed)


plugin = RequestTuner()
