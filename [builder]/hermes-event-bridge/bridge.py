"""Host-facing bridge: maps Hermes middleware/hook callbacks onto the protocol event chain.

Registers exactly ONE callback per host seam. The callback translates the host
call signature into a protocol event payload, runs the chain registry, and
returns the host-expected result shape. No host source is patched.

Host middleware signatures (hermes_cli/middleware.py):
  - llm_request:     cb(request, original_request, **ctx) -> {"request": {...}} | None
  - tool_request:    cb(tool_name, args, original_args, **ctx) -> {"args": {...}} | None
  - llm_execution:   cb(request, next_call, original_request, **ctx) -> Any
  - tool_execution:  cb(tool_name, args, next_call, original_args, **ctx) -> Any

Host hook signatures (hermes_cli/plugins.py):
  - pre_llm_call:    cb(**ctx) -> {"context": str} | None
  - pre_tool_call:   cb(**ctx) -> {"decision": "block", ...} | None
  - post_api_request: cb(**ctx) -> None
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from . import protocol
from .chain import ChainRegistry

logger = logging.getLogger("hermes-event-bridge.bridge")


def build_bridge_handlers(registry: ChainRegistry) -> Dict[str, Callable[..., Any]]:
    """Return the host callbacks to register. Keys are host seam names."""

    # ---- request class ---------------------------------------------------
    def llm_request_handler(request: Dict[str, Any], original_request: Dict[str, Any], **ctx: Any) -> Optional[Dict[str, Any]]:
        """Host llm_request middleware -> EVENT_REQUEST chain."""
        try:
            current = registry.run_request(
                protocol.EVENT_REQUEST,
                {"request": request, "original_request": original_request, **ctx},
                request,
            )
        except Exception as exc:  # noqa: BLE001 - never break the host
            logger.warning("hermes-event-bridge: llm_request chain failed: %s", exc)
            return None
        if current is request:
            return None  # no chain touched it -> skip (host semantics: None = unchanged)
        return protocol.request_replacement(current)

    def tool_request_handler(tool_name: str, args: Dict[str, Any], original_args: Dict[str, Any], **ctx: Any) -> Optional[Dict[str, Any]]:
        """Host tool_request middleware -> EVENT_TOOL_REQUEST chain."""
        try:
            current = registry.run_request(
                protocol.EVENT_TOOL_REQUEST,
                {"tool_name": tool_name, "args": args, "original_args": original_args, **ctx},
                args,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("hermes-event-bridge: tool_request chain failed: %s", exc)
            return None
        if current is args:
            return None
        return protocol.tool_args_replacement(current)

    # ---- execution class --------------------------------------------------
    def llm_exec_handler(request: Dict[str, Any], next_call: Callable[[Any], Any], original_request: Dict[str, Any], **ctx: Any) -> Any:
        """Host llm_execution middleware -> EVENT_REQUEST_EXEC chain, terminal = host next_call."""
        return registry.run_execution(
            protocol.EVENT_REQUEST_EXEC,
            {"request": request, "original_request": original_request, **ctx},
            next_call,
        )

    def tool_exec_handler(tool_name: str, args: Dict[str, Any], next_call: Callable[[Any], Any], original_args: Dict[str, Any], **ctx: Any) -> Any:
        """Host tool_execution middleware -> EVENT_TOOL_EXEC chain, terminal = host next_call."""
        return registry.run_execution(
            protocol.EVENT_TOOL_EXEC,
            {"tool_name": tool_name, "args": args, "original_args": original_args, **ctx},
            next_call,
        )

    # ---- observe class -----------------------------------------------------
    def pre_llm_call_handler(**ctx: Any) -> Optional[Dict[str, Any]]:
        """Host pre_llm_call hook -> EVENT_PRE_LLM_CALL chain (aggregate context)."""
        try:
            return registry.run_observe(protocol.EVENT_PRE_LLM_CALL, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("hermes-event-bridge: pre_llm_call chain failed: %s", exc)
            return None

    def pre_tool_call_handler(**ctx: Any) -> Optional[Dict[str, Any]]:
        """Host pre_tool_call hook -> EVENT_PRE_TOOL_CALL chain (block short-circuit)."""
        try:
            return registry.run_observe(protocol.EVENT_PRE_TOOL_CALL, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("hermes-event-bridge: pre_tool_call chain failed: %s", exc)
            return None

    def post_api_request_handler(**ctx: Any) -> None:
        """Host post_api_request hook -> EVENT_POST_API_REQUEST + EVENT_TURN_STOPPING notify."""
        try:
            registry.run_observe(protocol.EVENT_POST_API_REQUEST, ctx)
            registry.run_observe(protocol.EVENT_TURN_STOPPING, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.warning("hermes-event-bridge: post_api_request chain failed: %s", exc)
        return None

    return {
        "llm_request": llm_request_handler,
        "tool_request": tool_request_handler,
        "llm_execution": llm_exec_handler,
        "tool_execution": tool_exec_handler,
        "pre_llm_call": pre_llm_call_handler,
        "pre_tool_call": pre_tool_call_handler,
        "post_api_request": post_api_request_handler,
    }
