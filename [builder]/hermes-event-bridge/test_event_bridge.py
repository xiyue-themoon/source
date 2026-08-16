"""Self-contained verification for hermes-event-bridge core logic.

Tests ChainRegistry request/execution/observe semantics WITHOUT the Hermes
host (pure unit test). Run with the same interpreter the plugin will load
under. Exit code 0 = all pass.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from typing import Any, Callable, Dict, List

# Load the plugin the same way Hermes does: as hermes_plugins.<slug> with
# module.__path__ pointing at the plugin dir (so relative imports work).
_NS_PARENT = "hermes_plugins"
_plugin_dir = r"C:\Users\ROG\.hermes\plugins\hermes-event-bridge"
if _NS_PARENT not in sys.modules:
    ns_pkg = types.ModuleType(_NS_PARENT)
    ns_pkg.__path__ = []  # type: ignore[attr-defined]
    ns_pkg.__package__ = _NS_PARENT
    sys.modules[_NS_PARENT] = ns_pkg

_spec = importlib.util.spec_from_file_location(
    f"{_NS_PARENT}.hermes_event_bridge",
    rf"{_plugin_dir}\__init__.py",
    submodule_search_locations=[_plugin_dir],
)
_bridge = importlib.util.module_from_spec(_spec)
_bridge.__package__ = f"{_NS_PARENT}.hermes_event_bridge"
_bridge.__path__ = [_plugin_dir]  # type: ignore[attr-defined]
sys.modules[_bridge.__package__] = _bridge
_spec.loader.exec_module(_bridge)

protocol = _bridge.protocol
ChainRegistry = _bridge.chain.ChainRegistry

PASS = 0
FAIL = 0


def check(name: str, cond: bool) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


# --- chain plugin stubs -----------------------------------------------------

class NoopChain:
    name = "noop"
    events: List[str] = [protocol.EVENT_REQUEST, protocol.EVENT_PRE_LLM_CALL]

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        return None


class MaxTokensChain:
    name = "max_tokens"
    events: List[str] = [protocol.EVENT_REQUEST]

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        req = dict(ctx["request"])
        req["max_tokens"] = 32
        return protocol.request_replacement(req)


class TempChain:
    name = "temp"
    events: List[str] = [protocol.EVENT_REQUEST]

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        req = dict(ctx["request"])
        req["temperature"] = 0.5
        return protocol.request_replacement(req)


class BlockChain:
    name = "blocker"
    events: List[str] = [protocol.EVENT_PRE_TOOL_CALL]

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        if ctx.get("tool_name") == "web_search":
            return protocol.block_decision("blocked by test")
        return None


class ContextChain:
    name = "ctx1"
    events: List[str] = [protocol.EVENT_PRE_LLM_CALL]

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        return protocol.context_injection("source-1")


class ContextChain2:
    name = "ctx2"
    events: List[str] = [protocol.EVENT_PRE_LLM_CALL]

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        return protocol.context_injection("source-2")


class ExecChain:
    name = "exec_wrap"
    events: List[str] = [protocol.EVENT_REQUEST_EXEC]

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        payload = ctx["request"]
        payload["wrapped"] = True
        return await next_call(payload)


class ExplodingChain:
    name = "exploder"
    events: List[str] = [protocol.EVENT_REQUEST, protocol.EVENT_PRE_LLM_CALL]

    async def handle(self, ctx: Dict[str, Any], next_call: Callable[..., Any]) -> Any:
        raise RuntimeError("intentional test failure")


# --- tests ------------------------------------------------------------------

print("== T1: empty chain -> default passthrough ==")
reg = ChainRegistry()
out = reg.run_request(protocol.EVENT_REQUEST, {"request": {"model": "x"}}, {"model": "x"})
check("request unchanged", out == {"model": "x"})
check("no chains subscribed", reg.subscribed(protocol.EVENT_REQUEST) == [])

print("== T2: request chain order overwrite ==")
reg = ChainRegistry()
reg.register(MaxTokensChain())
reg.register(TempChain())
out = reg.run_request(protocol.EVENT_REQUEST, {"request": {"model": "x"}}, {"model": "x"})
check("max_tokens set by A", out.get("max_tokens") == 32)
check("temperature set by B (later chain wins)", out.get("temperature") == 0.5)
check("model preserved", out.get("model") == "x")

print("== T3: request chain - A's change preserved when B doesn't touch it ==")
reg = ChainRegistry()
reg.register(MaxTokensChain())
reg.register(NoopChain())
out = reg.run_request(protocol.EVENT_REQUEST, {"request": {"model": "x"}}, {"model": "x"})
check("max_tokens survives B noop", out.get("max_tokens") == 32)

print("== T4: observe pre-tool-call block short-circuit ==")
reg = ChainRegistry()
reg.register(BlockChain())
block = reg.run_observe(protocol.EVENT_PRE_TOOL_CALL, {"tool_name": "web_search"})
check("web_search blocked", block is not None and block.get("decision") == "block")
other = reg.run_observe(protocol.EVENT_PRE_TOOL_CALL, {"tool_name": "read_file"})
check("read_file not blocked", other is None)

print("== T5: observe pre-llm-call multi-source merge ==")
reg = ChainRegistry()
reg.register(ContextChain())
reg.register(ContextChain2())
merged = reg.run_observe(protocol.EVENT_PRE_LLM_CALL, {})
check("two sources merged", merged is not None and "source-1" in merged["context"] and "source-2" in merged["context"])

print("== T6: execution chain wraps terminal ==")
reg = ChainRegistry()
reg.register(ExecChain())
called = []

def terminal(payload: Any) -> Any:
    called.append(payload)
    return "terminal-result"

result = reg.run_execution(protocol.EVENT_REQUEST_EXEC, {"request": {"model": "x"}}, terminal)
check("terminal called", len(called) == 1)
check("payload wrapped before terminal", called[0].get("wrapped") is True)
check("result returned", result == "terminal-result")

print("== T7: exploding chain does not break the chain ==")
reg = ChainRegistry()
reg.register(ExplodingChain())
reg.register(MaxTokensChain())
out = reg.run_request(protocol.EVENT_REQUEST, {"request": {"model": "x"}}, {"model": "x"})
check("exploder skipped, later chain still runs", out.get("max_tokens") == 32)

print("== T8: protocol validation rejects unknown event ==")
try:
    protocol.validate_event_name("agent/bogus")
    check("unknown event rejected", False)
except ValueError:
    check("unknown event rejected", True)

print()
print(f"RESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
