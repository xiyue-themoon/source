# hermes-event-bridge

Zero-patch Hermes plugin implementing Event Protocol v1 — exposes the host's
native middleware/hook seams as a unified `agent/*` event chain for user chain
plugins. No host source is patched; survives Hermes upgrades.

Status: [builder] implemented + verified (2026-08-16), protocol v1 locked with Pioneer.

## What it does

- Registers 4 host middleware (`llm_request`, `tool_request`, `llm_execution`,
  `tool_execution`) + 3 host hooks (`pre_llm_call`, `pre_tool_call`,
  `post_api_request`) — one callback per seam.
- Routes host callbacks through a `ChainRegistry` that dispatches to user
  chain plugins (`chains/*.py`, auto-discovered, each exposing `plugin`).
- Chain semantics per event class:
  - request class (`agent/request`, `agent/tool-request`): sequential overwrite
  - execution class (`agent/request-exec`, `agent/tool-exec`): async next_call chain
  - observe class (`agent/pre-llm-call`, `agent/pre-tool-call`,
    `agent/post-api-request`, `agent/turn-stopping`): merge / short-circuit / notify

## Files

| File | Purpose |
|:-----|:--------|
| `plugin.yaml` | Hermes plugin manifest |
| `protocol.py` | Event names, payload contracts, ChainPlugin interface (pure, host-free) |
| `bridge.py` | Host callback factories — one per host seam |
| `chain.py` | ChainRegistry — ordered dispatch + observe aggregation |
| `chains/` | User chain plugins (auto-discovered) |
| `test_event_bridge.py` | Self-contained unit tests (no Hermes host needed) |

## Install

1. Copy this directory to `~/AppData/Local/hermes/plugins/hermes-event-bridge/`
   (on Windows: `C:\Users\<user>\AppData\Local\hermes\plugins\`).
2. `hermes plugins enable hermes-event-bridge`
3. Add chain plugins under `chains/` (each exposes `plugin`, a
   `protocol.ChainPlugin` instance).

## Chain plugin contract

```python
class MyChain:
    name = "my_chain"
    events = ["agent/request"]  # see protocol.ALL_EVENTS

    async def handle(self, ctx: dict, next_call: Callable) -> Any:
        # request class: return {"request": {...}} or None
        # execution class: call await next_call(payload) or short-circuit
        # observe class: return {"context": str} / {"decision": "block", ...} / None
        ...
```

## Env tunables (example chains)

- `HERMES_EVENT_BRIDGE_MAX_TOKENS` — request_tuner overrides max_tokens
- `HERMES_EVENT_BRIDGE_BLOCKED_TOOLS` — tool_guard comma-separated block list
- `HERMES_EVENT_BRIDGE_CONTEXT` — context_injector marker text

## Verification (matrix from protocol v1)

| # | Item | Result |
|:-:|:-----|:------:|
| 1 | empty chain zero regression | PASS |
| 2 | request chain effective (max_tokens) | PASS |
| 3 | multi-chain order overwrite | PASS |
| 4 | tool block short-circuit | PASS |
| 5 | context multi-source merge | PASS |
| 6 | execution wrap | PASS |
| 7 | upgrade compat (exception containment) | PASS |

Run unit tests: `python test_event_bridge.py` (14 checks, all pass).

## Protocol reference

Event Protocol v1: `Hermes-事件协议-v1.md` (Pioneer-authored, locked).
Architecture notes: hermes-notes 情报-推理与Agent框架.md C6/C7.
