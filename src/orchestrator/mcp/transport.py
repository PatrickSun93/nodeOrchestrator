"""MCPTransport: sync bridge over the async MCP SDK (ADR-027 D1, ADR-031 D2, ADR-032 D2).

Dispatches to the appropriate async transport:
  stdio          — subprocess_mcp_stdio (mcp/subprocess_trust.py)
  streamable_http — streamable_http_client + host-built httpx.AsyncClient (ADR-032 D2)

Shared bridge machinery: mcp/_async_bridge.run_sync() wraps every call in a
fresh event loop + asyncio.wait_for() bounded timeout (transport-agnostic seam,
R0-A G1; reused by both stdio and remote paths).

Subprocess trust machinery: mcp/subprocess_trust.py owns the child process,
tracks its PID, adds the LAYER-1 kill watchdog after SDK teardown (ADR-031 D2).

Remote trust surface (ADR-032 D3): TLS verify=True (explicit, never disabled);
URL allowlist via config; credential via api_key_env → Authorization header (never
logged/inline); bounded httpx timeout; fail-closed on any failure mode.

No routing / judgment here — transport + adapter only (HR#6).
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
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
    """Sync bridge to an MCP server (ADR-027 D1, ADR-031 D2, ADR-032 D2).

    Per-operation connections for stdio — each list_tools() / call_tool() spawns a
    subprocess via subprocess_mcp_stdio, communicates, then tears down.
    Per-operation connections for streamable_http — each call opens a new HTTP
    request via the non-deprecated streamable_http_client + a host-built
    httpx.AsyncClient(verify=True, ...) (ADR-032 D2; bring-your-own-client contract).

    asyncio.wait_for() enforces bounded timeouts via run_sync() (_async_bridge).
    Fail-closed on every error mode (MCPTimeoutError / MCPConnectionError).
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

    # ------------------------------------------------------------------
    # stdio helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # remote helpers (ADR-032 D2)
    # ------------------------------------------------------------------

    def _remote_auth_headers(self) -> dict[str, str]:
        """Build Authorization header from api_key_env (credential-via-env, HR#5).

        Returns {} if api_key_env is not set or the env var is absent.
        Never logs or inlines the secret.
        """
        if not self._server_cfg.api_key_env:
            return {}
        secret = os.environ.get(self._server_cfg.api_key_env)
        if not secret:
            return {}
        return {"Authorization": f"Bearer {secret}"}

    def _remote_client_for_list(self) -> httpx.AsyncClient:
        """Host-built AsyncClient for list_tools (verify=True, bounded timeout)."""
        return httpx.AsyncClient(
            verify=True,
            headers=self._remote_auth_headers(),
            timeout=httpx.Timeout(
                connect=self._timeouts.connect,
                read=self._timeouts.list_tools,
                write=self._timeouts.list_tools,
                pool=self._timeouts.connect,
            ),
        )

    def _remote_client_for_call(self) -> httpx.AsyncClient:
        """Host-built AsyncClient for call_tool (verify=True, bounded timeout)."""
        return httpx.AsyncClient(
            verify=True,
            headers=self._remote_auth_headers(),
            timeout=httpx.Timeout(
                connect=self._timeouts.connect,
                read=self._timeouts.call_tool,
                write=self._timeouts.call_tool,
                pool=self._timeouts.connect,
            ),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def list_tools(self) -> list[Tool]:
        """Connect → initialize → list tools → teardown. Bounded timeout."""
        total = self._timeouts.connect + self._timeouts.list_tools
        coro = (
            self._async_list_tools_remote()
            if self._server_cfg.transport == "streamable_http"
            else self._async_list_tools()
        )
        return run_sync(
            coro,
            timeout=total,
            timeout_msg=(f"Server {self._server_name!r}: list_tools timed out after {total:.0f}s"),
            error_msg_prefix=f"Server {self._server_name!r}: list_tools failed",
        )

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Connect → initialize → call tool → teardown. Bounded timeout."""
        total = self._timeouts.connect + self._timeouts.call_tool
        coro = (
            self._async_call_tool_remote(tool_name, arguments)
            if self._server_cfg.transport == "streamable_http"
            else self._async_call_tool(tool_name, arguments)
        )
        return run_sync(
            coro,
            timeout=total,
            timeout_msg=(
                f"Server {self._server_name!r}: call_tool({tool_name!r}) timed out "
                f"after {total:.0f}s"
            ),
            error_msg_prefix=(f"Server {self._server_name!r}: call_tool({tool_name!r}) failed"),
        )

    # ------------------------------------------------------------------
    # stdio async implementation
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Remote (streamable-http) async implementation (ADR-032 D2)
    # ------------------------------------------------------------------

    async def _async_list_tools_remote(self) -> list[Tool]:
        """streamable-http list_tools: host-built AsyncClient(verify=True) + SDK client."""
        url = self._server_cfg.url
        if url is None:
            raise MCPConnectionError(
                f"Server {self._server_name!r}: streamable_http transport has no url"
            )
        async with (
            self._remote_client_for_list() as http_client,
            streamable_http_client(url, http_client=http_client) as (
                read,
                write,
                _get_session_id,  # per-op connections; session id unused in MVP
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.list_tools()
            return list(result.tools)

    async def _async_call_tool_remote(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        """streamable-http call_tool: host-built AsyncClient(verify=True) + SDK client."""
        url = self._server_cfg.url
        if url is None:
            raise MCPConnectionError(
                f"Server {self._server_name!r}: streamable_http transport has no url"
            )
        async with (
            self._remote_client_for_call() as http_client,
            streamable_http_client(url, http_client=http_client) as (
                read,
                write,
                _get_session_id,  # per-op connections; session id unused in MVP
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await session.call_tool(tool_name, arguments)
