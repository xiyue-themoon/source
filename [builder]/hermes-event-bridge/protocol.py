"""Event protocol v1 - shared event names, payload contracts, and chain plugin interface.

Defines the agent/* event vocabulary both Hermes hosts (Builder Win11, Pioneer cloud)
use to speak the same protocol. This module is pure - no host imports, so it can be
imported by tests and by chain plugins without triggering plugin discovery.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Event names (namespace agent/*, aligned with deepseek-harness semantics)
# ---------------------------------------------------------------------------

# request class - waterfall (host native middleware), order overwrites
EVENT_REQUEST = "agent/request"           # llm_request middleware
EVENT_TOOL_REQUEST = "agent/tool-request"  # tool_request middleware

# execution class - waterfall with next_call (host native middleware chain)
EVENT_REQUEST_EXEC = "agent/request-exec"  # llm_execution middleware
EVENT_TOOL_EXEC = "agent/tool-exec"        # tool_execution middleware

# observe class - emit (host hook), aggregated by bridge chain
EVENT_PRE_LLM_CALL = "agent/pre-llm-call"       # pre_llm_call hook
EVENT_PRE_TOOL_CALL = "agent/pre-tool-call"     # pre_tool_call hook
EVENT_POST_API_REQUEST = "agent/post-api-request"  # post_api_request hook
EVENT_TURN_STOPPING = "agent/turn-stopping"     # approximated via post_api_request + accumulation

# All events a chain plugin may subscribe to.
ALL_EVENTS: List[str] = [
    EVENT_REQUEST,
    EVENT_TOOL_REQUEST,
    EVENT_REQUEST_EXEC,
    EVENT_TOOL_EXEC,
    EVENT_PRE_LLM_CALL,
    EVENT_PRE_TOOL_CALL,
    EVENT_POST_API_REQUEST,
    EVENT_TURN_STOPPING,
]

# ---------------------------------------------------------------------------
# Host middleware kinds (hermes_cli.middleware.VALID_MIDDLEWARE)
# ---------------------------------------------------------------------------

HOST_MW_LLM_REQUEST = "llm_request"
HOST_MW_TOOL_REQUEST = "tool_request"
HOST_MW_LLM_EXECUTION = "llm_execution"
HOST_MW_TOOL_EXECUTION = "tool_execution"

# Host hook names (hermes_cli.plugins.VALID_HOOKS)
HOST_HOOK_PRE_LLM_CALL = "pre_llm_call"
HOST_HOOK_PRE_TOOL_CALL = "pre_tool_call"
HOST_HOOK_POST_API_REQUEST = "post_api_request"

# ---------------------------------------------------------------------------
# Return contract shapes
# ---------------------------------------------------------------------------

def request_replacement(request: Dict[str, Any]) -> Dict[str, Any]:
    """Return shape for EVENT_REQUEST handlers: replace provider kwargs."""
    return {"request": request}


def tool_args_replacement(args: Dict[str, Any]) -> Dict[str, Any]:
    """Return shape for EVENT_TOOL_REQUEST handlers: replace tool args."""
    return {"args": args}


def block_decision(message: str) -> Dict[str, Any]:
    """Return shape for EVENT_PRE_TOOL_CALL handlers: short-circuit block.

    v1.1 contract fix (2026-08-16, cloud verification): the HOST
    (get_pre_tool_call_directive, plugins.py L2157-2173) parses the ``action``
    key - {"decision": "block"} is silently ignored. We return BOTH keys so the
    host reads ``action`` and chain code / tests can read ``decision``.
    """
    return {"action": "block", "decision": "block", "message": message}


def context_injection(context: str) -> Dict[str, Any]:
    """Return shape for EVENT_PRE_LLM_CALL handlers: context to merge into user message."""
    return {"context": context}


# ---------------------------------------------------------------------------
# Chain plugin interface (chains/*.py must implement this)
# ---------------------------------------------------------------------------

@runtime_checkable
class ChainPlugin(Protocol):
    """Contract every user chain plugin implements.

    - request class: handle() returns {"request": {...}} or {"args": {...}} or None
    - execution class: handle() calls next_call(payload) to continue, or returns a result to short-circuit
    - observe class: handle() returns {"context": str} / {"decision": "block", ...} / None
    """

    name: str
    events: List[str]

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        """Process one event. ctx is the event payload; next_call continues the chain."""
        ...


# ---------------------------------------------------------------------------
# Payload validation helpers
# ---------------------------------------------------------------------------

def validate_event_name(event: str) -> None:
    """Raise ValueError on unknown event names (catches typos at registration)."""
    if event not in ALL_EVENTS:
        raise ValueError(
            f"hermes-event-bridge: unknown event {event!r}; "
            f"valid: {', '.join(sorted(ALL_EVENTS))}"
        )
