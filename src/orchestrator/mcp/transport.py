"""MCPTransport: sync bridge over the async MCP SDK (ADR-027 D1, ADR-031 D2, ADR-032 D2).

Dispatches to the appropriate async transport:
  stdio       — subprocess_mcp_stdio (mcp/subprocess_trust.py)
  streamable_http — streamable_http_client (added in P3.7-remote-2)

Shared bridge machinery: mcp/_async_bridge.run_sync() wraps every call in a
fresh event loop + asyncio.wait_for() bounded timeout (transport-agnostic seam,
R0-A G1; reused by both stdio and remote paths).

Subprocess trust machinery: mcp/subprocess_trust.py owns the child process,
tracks its PID, adds the LAYER-1 kill watchdog after SDK teardown (ADR-031 D2).

No routing / judgment here — transport + adapter only (HR#6).
"""

from __future__ import annotations

from typing import Any

from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult, Tool

from mcp import ClientSession
from orchestrator.mcp._async_bridge import (
    MCPConnectionError,
    MCPError,
    MCPTimeoutError,
    run_sync,
)
from orchestrator.mcp.config import MCPServerConfig, MCPTimeouts
from orchestrator.mcp.subprocess_trust import build_scoped_env, subprocess_mcp_stdio

# Backward-compatible alias (tests import _build_scoped_env from this module).
_build_scoped_env = build_scoped_env

# Re-export for backward compat (execution.py + tests import MCPError* from here).
__all__ = [
    "MCPConnectionError",
    "MCPError",
    "MCPTimeoutError",
    "MCPTransport",
    "_build_scoped_env",
]


class MCPTransport:
    """Sync bridge to an MCP server (ADR-027 D1, ADR-031 D2).

    Per-operation connections for stdio — each list_tools() / call_tool() spawns a
    subprocess via subprocess_mcp_stdio, communicates, then tears down.
    asyncio.wait_for() enforces bounded timeouts via run_sync() (_async_bridge).

    The stdio path uses subprocess_mcp_stdio which:
    - Owns the child process and tracks its PID.
    - Adds LAYER-1 kill watchdog after SDK teardown (no orphan guarantee).
    - Provides minimal-scoped child env (no orchestrator secrets).

    Remote streamable-http path is added in P3.7-remote-2.
    """

    def __init__(
        self,
        server_name: str,
        server_cfg: MCPServerConfig,
        timeouts: MCPTimeouts | None = None,
    ) -> None:
        self._server_name = server_name
        self._server_cfg = server_cfg
        self._timeouts = timeouts if timeouts is not None else server_cfg.timeouts

    def _make_params(self) -> StdioServerParameters:
        command = self._server_cfg.command
        if command is None:
            raise MCPConnectionError(
                f"Server {self._server_name!r}: stdio transport has no command"
            )
        return StdioServerParameters(
            command=command,
            args=list(self._server_cfg.args),
            env=build_scoped_env(self._server_cfg),
        )

    def list_tools(self) -> list[Tool]:
        """Spawn → initialize → list tools → teardown. Bounded timeout."""
        total = self._timeouts.connect + self._timeouts.list_tools
        return run_sync(
            self._async_list_tools(),
            timeout=total,
            timeout_msg=(f"Server {self._server_name!r}: list_tools timed out after {total:.0f}s"),
            error_msg_prefix=f"Server {self._server_name!r}: list_tools failed",
        )

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Spawn → initialize → call tool → teardown. Bounded timeout."""
        total = self._timeouts.connect + self._timeouts.call_tool
        return run_sync(
            self._async_call_tool(tool_name, arguments),
            timeout=total,
            timeout_msg=(
                f"Server {self._server_name!r}: call_tool({tool_name!r}) timed out "
                f"after {total:.0f}s"
            ),
            error_msg_prefix=(f"Server {self._server_name!r}: call_tool({tool_name!r}) failed"),
        )

    async def _async_list_tools(self) -> list[Tool]:
        params = self._make_params()
        async with (
            subprocess_mcp_stdio(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.list_tools()
            return list(result.tools)

    async def _async_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> CallToolResult:
        params = self._make_params()
        async with (
            subprocess_mcp_stdio(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await session.call_tool(tool_name, arguments)
