"""hermes-event-bridge - Event protocol v1 host bridge.

Zero-patch Hermes plugin that exposes the host's native middleware/hook seams
as a unified agent/* event chain. User chain plugins live in chains/ and
implement protocol.ChainPlugin; they are discovered automatically.

Layout:
    plugin.yaml   - manifest (name/description/hooks)
    protocol.py   - event names, payload contracts, ChainPlugin interface
    bridge.py     - host callback factories (one callback per host seam)
    chain.py      - ChainRegistry: ordered dispatch + observe aggregation
    chains/       - user chain plugins (auto-discovered, one file each)

Usage:
    The plugin auto-registers on Hermes plugin discovery. Chain plugins in
    chains/ are loaded automatically; each file must expose `plugin` (a
    protocol.ChainPlugin instance). Disable individual chains by removing
    them from chains/ or renaming the file.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from . import bridge, protocol
from .chain import ChainRegistry

logger = logging.getLogger("hermes-event-bridge")


def _discover_chains(registry: ChainRegistry) -> None:
    """Import every module in chains/ and register its exported `plugin`."""
    from . import chains as chains_pkg  # noqa: PLC0415 - local import avoids circulars

    for mod_info in pkgutil.iter_modules(chains_pkg.__path__):
        if mod_info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{chains_pkg.__name__}.{mod_info.name}")
        except Exception as exc:  # noqa: BLE001 - one bad chain must not kill the bridge
            logger.warning("hermes-event-bridge: failed to import chain %s: %s", mod_info.name, exc)
            continue
        plugin = getattr(mod, "plugin", None)
        if plugin is None:
            logger.warning("hermes-event-bridge: chain %s has no `plugin` export; skipped", mod_info.name)
            continue
        try:
            registry.register(plugin)
        except Exception as exc:  # noqa: BLE001
            logger.warning("hermes-event-bridge: failed to register chain %s: %s", mod_info.name, exc)


def register(ctx: Any) -> None:
    """Hermes plugin entry point: register one callback per host seam."""
    registry = ChainRegistry()
    _discover_chains(registry)

    handlers = bridge.build_bridge_handlers(registry)

    # request/execution class -> host middleware (VALID_MIDDLEWARE kinds)
    ctx.register_middleware(protocol.HOST_MW_LLM_REQUEST, handlers["llm_request"])
    ctx.register_middleware(protocol.HOST_MW_TOOL_REQUEST, handlers["tool_request"])
    ctx.register_middleware(protocol.HOST_MW_LLM_EXECUTION, handlers["llm_execution"])
    ctx.register_middleware(protocol.HOST_MW_TOOL_EXECUTION, handlers["tool_execution"])

    # observe class -> host hooks
    ctx.register_hook(protocol.HOST_HOOK_PRE_LLM_CALL, handlers["pre_llm_call"])
    ctx.register_hook(protocol.HOST_HOOK_PRE_TOOL_CALL, handlers["pre_tool_call"])
    ctx.register_hook(protocol.HOST_HOOK_POST_API_REQUEST, handlers["post_api_request"])

    logger.info(
        "hermes-event-bridge: registered 4 middleware + 3 hooks; %d chain plugin(s)",
        len(registry._plugins),
    )
