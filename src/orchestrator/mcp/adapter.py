"""MCP tool-adapter: builds the namespaced ToolMeta registry from config allowlist.

Public API:
  namespace(server, tool)                          → "mcp__<server>__<tool>"
  to_mcp_call(namespaced_name)                     → (server_name, tool_name)
  build_tool_registry(server, cfg, discovered)     → dict[str, ToolMeta]
  build_mcp_tool_registry_from_config(config_path) → dict[str, ToolMeta]

Namespacing: mcp__<server>__<tool> (double-underscore, collision-free vs local
tools which never carry the mcp__ prefix; ADR-027 D3).

Classification: config reversibility only; server hints (readOnlyHint etc.)
are ignored entirely (HR#2).

Discovery ≠ permission: only tools present in the config allowlist are
registered. Discovered-but-unclassified tools get no ToolMeta → they will
raise UnknownToolError when called (HR#3, fail-closed).

No routing / judgment here (HR#6). No LLM calls.
"""

from __future__ import annotations

import logging
from pathlib import Path

from mcp.types import Tool

from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.mcp.config import MCPServerConfig, load_mcp_servers_config

_log = logging.getLogger("orchestrator.mcp.adapter")

_MCP_PREFIX = "mcp__"


class AdapterError(Exception):
    """Raised for namespacing or config errors."""


def namespace(server_name: str, tool_name: str) -> str:
    """Produce the canonical namespaced tool key: mcp__<server>__<tool>."""
    return f"{_MCP_PREFIX}{server_name}__{tool_name}"


def to_mcp_call(namespaced_name: str) -> tuple[str, str]:
    """Reverse namespace: 'mcp__<server>__<tool>' → (server_name, tool_name).

    Raises AdapterError if the name is not a valid MCP-namespaced tool.
    """
    if not namespaced_name.startswith(_MCP_PREFIX):
        raise AdapterError(
            f"Not an MCP-namespaced tool: {namespaced_name!r} (expected mcp__<server>__<tool>)"
        )
    tail = namespaced_name[len(_MCP_PREFIX) :]
    parts = tail.split("__", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise AdapterError(
            f"Malformed MCP tool name: {namespaced_name!r} (expected mcp__<server>__<tool>)"
        )
    return parts[0], parts[1]


def build_tool_registry(
    server_name: str,
    server_cfg: MCPServerConfig,
    discovered_tools: list[Tool],
) -> dict[str, ToolMeta]:
    """Build namespaced ToolMeta entries for allowlisted tools (ADR-027 D3).

    Only tools present in server_cfg.tools (the pre-classify allowlist) are
    registered. Discovered-but-unclassified tools are skipped — they will
    raise UnknownToolError when called (discovery ≠ permission, HR#3).

    Server hints (readOnlyHint / destructiveHint) are ignored; reversibility
    comes from the config value only (HR#2).

    Returns dict keyed by "mcp__<server>__<tool>".
    """
    discovered_names = {t.name for t in discovered_tools}
    registry: dict[str, ToolMeta] = {}

    for tool_name, tool_cfg in server_cfg.tools.items():
        if tool_name not in discovered_names:
            # Allowlisted but not discovered — server doesn't expose it; skip.
            _log.debug(
                "mcp adapter: server=%r tool=%r allowlisted but not discovered; skipping",
                server_name,
                tool_name,
            )
            continue
        key = namespace(server_name, tool_name)
        registry[key] = ToolMeta(reversibility=tool_cfg.reversibility)

    return registry


def build_mcp_tool_registry_from_config(
    config_path: Path,
    *,
    skip_unavailable: bool = True,
) -> dict[str, ToolMeta]:
    """Load mcp_servers.yaml and build the full namespaced ToolMeta registry.

    Connects to each configured server, discovers tools, and registers
    allowlisted tools. If skip_unavailable=True (default), servers that fail
    to connect are warned and skipped (graceful degradation at startup).

    Raises MCPConnectionError / MCPTimeoutError only when skip_unavailable=False.
    """
    from orchestrator.mcp.client import connect, list_tools  # local import: avoids cycles

    if not config_path.exists():
        return {}

    cfg = load_mcp_servers_config(config_path)
    registry: dict[str, ToolMeta] = {}

    for server_name, server_cfg in cfg.servers.items():
        try:
            session = connect(server_name, server_cfg)
            discovered = list_tools(session)
            server_registry = build_tool_registry(server_name, server_cfg, discovered)
            registry.update(server_registry)
            _log.info(
                "mcp adapter: server=%r registered %d tools",
                server_name,
                len(server_registry),
            )
        except Exception as exc:
            if skip_unavailable:
                _log.warning(
                    "mcp adapter: server=%r unavailable at startup (%s); skipping",
                    server_name,
                    exc,
                )
            else:
                raise

    return registry
