"""Chain registry and aggregation for observe-class events.

Hermes host hooks are emit-collect: every registered callback fires and its
non-None return values are collected in order. The bridge installs ONE host
callback per observe event, then aggregates multiple user chain plugins into
an ordered merge:

- EVENT_PRE_LLM_CALL:   merge all {"context": str} contributions, join with blank line
- EVENT_PRE_TOOL_CALL:  first non-None block decision short-circuits
- EVENT_POST_API_REQUEST / EVENT_TURN_STOPPING: notification only
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from . import protocol

logger = logging.getLogger("hermes-event-bridge.chain")


class ChainRegistry:
    """Holds user chain plugins and dispatches events to them in registration order."""

    def __init__(self) -> None:
        self._plugins: List[protocol.ChainPlugin] = []

    def register(self, plugin: protocol.ChainPlugin) -> None:
        """Register a chain plugin. Order = registration order (first wins for observe merge)."""
        for ev in plugin.events:
            protocol.validate_event_name(ev)
        self._plugins.append(plugin)
        logger.info("hermes-event-bridge: registered chain plugin %s (%s)", plugin.name, ",".join(plugin.events))

    def subscribed(self, event: str) -> List[protocol.ChainPlugin]:
        return [p for p in self._plugins if event in p.events]

    # -- request class: host middleware is already sequential-overwrite; the bridge
    #    forwards the current payload through each subscribed chain plugin in order.
    def run_request(self, event: str, ctx: Dict[str, Any], default: Dict[str, Any]) -> Dict[str, Any]:
        current = default
        for plugin in self.subscribed(event):
            try:
                result = _await(plugin.handle({**ctx, "request": current}, _noop_next))
            except Exception as exc:  # noqa: BLE001 - contract: chains never propagate
                logger.warning("hermes-event-bridge: chain %s failed on %s: %s", plugin.name, event, exc)
                continue
            if isinstance(result, dict):
                if "request" in result and isinstance(result["request"], dict):
                    current = result["request"]
                elif "args" in result and isinstance(result["args"], dict):
                    current = result["args"]
        return current

    # -- execution class: build a next_call chain over subscribed plugins, ending at host terminal.
    def run_execution(self, event: str, ctx: Dict[str, Any], terminal: Callable[[Any], Any]) -> Any:
        plugins = self.subscribed(event)

        async def call_at(index: int, payload: Any) -> Any:
            if index >= len(plugins):
                return terminal(payload)
            plugin = plugins[index]
            next_called = False

            async def next_call(next_payload: Any = None) -> Any:
                nonlocal next_called
                if next_called:
                    raise RuntimeError(
                        f"hermes-event-bridge: chain {plugin.name} called next_call twice on {event}"
                    )
                next_called = True
                return await call_at(index + 1, payload if next_payload is None else next_payload)

            try:
                return await plugin.handle({**ctx, "request": payload}, next_call)
            except Exception as exc:  # noqa: BLE001
                logger.warning("hermes-event-bridge: chain %s failed on %s: %s", plugin.name, event, exc)
                if next_called:
                    # next_call already ran downstream; the exception happened after it
                    # (or inside the plugin after delegating) - re-raise to avoid a
                    # silently swallowed terminal result.
                    raise
                return await call_at(index + 1, payload)

        return _await(call_at(0, ctx.get("request") if "request" in ctx else ctx.get("args")))

    # -- observe class: merge / short-circuit / notify.
    def run_observe(self, event: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if event == protocol.EVENT_PRE_LLM_CALL:
            return self._merge_contexts(ctx)
        if event == protocol.EVENT_PRE_TOOL_CALL:
            return self._first_block(ctx)
        # notification events: fire and forget
        for plugin in self.subscribed(event):
            try:
                _await(plugin.handle(ctx, _noop_next))
            except Exception as exc:  # noqa: BLE001
                logger.warning("hermes-event-bridge: chain %s failed on %s: %s", plugin.name, event, exc)
        return None

    def _merge_contexts(self, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        parts: List[str] = []
        for plugin in self.subscribed(protocol.EVENT_PRE_LLM_CALL):
            try:
                result = _await(plugin.handle(ctx, _noop_next))
            except Exception as exc:  # noqa: BLE001
                logger.warning("hermes-event-bridge: chain %s failed on pre-llm-call: %s", plugin.name, exc)
                continue
            if isinstance(result, dict) and isinstance(result.get("context"), str) and result["context"]:
                parts.append(result["context"])
        if not parts:
            return None
        return protocol.context_injection("\n\n".join(parts))

    def _first_block(self, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for plugin in self.subscribed(protocol.EVENT_PRE_TOOL_CALL):
            try:
                result = _await(plugin.handle(ctx, _noop_next))
            except Exception as exc:  # noqa: BLE001
                logger.warning("hermes-event-bridge: chain %s failed on pre-tool-call: %s", plugin.name, exc)
                continue
            if isinstance(result, dict) and result.get("decision") == "block":
                return result
        return None


def _await(value: Any) -> Any:
    """Resolve a coroutine transparently, blocking the calling thread.

    Host seams are synchronous callers (plugins.py invoke_hook is a sync def
    that does NOT await; middleware _run_execution_chain returns callback()
    synchronously). Chain plugins declare async handle(), so the bridge must
    resolve coroutines to concrete values before returning to the host.

    - No running loop (CLI / worker thread): asyncio.run() directly.
    - Running loop present (gateway thread executing middleware synchronously):
      drive the coroutine in an executor thread and block on its future - this
      does not deadlock the running loop and returns the concrete value.
    """
    if not hasattr(value, "__await__"):
        return value
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    loop = asyncio.get_running_loop()

    def _drive() -> Any:
        try:
            return asyncio.run(value)
        except RuntimeError:
            # Extremely defensive: fresh loop if asyncio.run refuses.
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(value)
            finally:
                new_loop.close()

    return loop.run_in_executor(None, _drive).result()


def _noop_next(*args: Any, **kwargs: Any) -> Any:
    """Fallback next_call for observe events (no chain continuation)."""
    raise RuntimeError("hermes-event-bridge: next_call is not available for observe-class events")
