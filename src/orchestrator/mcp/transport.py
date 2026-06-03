"""MCPTransport: sync bridge over the async MCP stdio SDK (ADR-027 D1).

Per-operation subprocess connections (MVP): each list_tools() / call_tool()
spawns a fresh subprocess, communicates, then tears down.

Bounded timeouts: every SDK call is wrapped in asyncio.wait_for().
On TimeoutError: asyncio.wait_for cancels the coroutine → the
stdio_client async context manager __aexit__ closes stdin and then
SIGTERM → SIGKILL the subprocess (no orphan; the MCP SDK's
PROCESS_TERMINATION_TIMEOUT handles escalation). The orchestrator
thread is never blocked indefinitely.

Scoped env: subprocess gets only safe base keys + server.env + api_key_env
secret — NOT the orchestrator's full environment (HR#10; the P2.7-S3
c2 env-inheritance lesson).

No routing / judgment here — transport + adapter only (HR#6).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, Tool

from mcp import ClientSession
from orchestrator.mcp.config import MCPServerConfig, MCPTimeouts

# Safe env keys to inherit in the subprocess (HR#10 minimal-scoped env).
_SAFE_ENV_KEYS: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TERM",
    "TMPDIR",
    "TEMP",
    "TMP",
)


class MCPError(Exception):
    """Base class for MCP transport errors."""


class MCPTimeoutError(MCPError):
    """SDK call timed out; subprocess killed by stdio_client cleanup (HR#10)."""


class MCPConnectionError(MCPError):
    """Failed to connect or initialize the MCP server."""


def _build_scoped_env(server_cfg: MCPServerConfig) -> dict[str, str]:
    """Construct minimal scoped subprocess env (HR#10).

    Never passes the orchestrator's full os.environ.
    """
    env: dict[str, str] = {}
    for key in _SAFE_ENV_KEYS:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    env.update(server_cfg.env)
    if server_cfg.api_key_env:
        secret = os.environ.get(server_cfg.api_key_env)
        if secret is not None:
            env[server_cfg.api_key_env] = secret
    return env


class MCPTransport:
    """Sync bridge to an MCP stdio server subprocess (ADR-027 D1).

    Per-operation connections — each list_tools() / call_tool() spawns a
    subprocess, runs via the official mcp Python SDK, then tears down.
    asyncio.wait_for() enforces bounded timeouts; on TimeoutError the
    stdio_client context manager kills the subprocess (no orphan).
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
        return StdioServerParameters(
            command=self._server_cfg.command,
            args=list(self._server_cfg.args),
            env=_build_scoped_env(self._server_cfg),
        )

    def list_tools(self) -> list[Tool]:
        """Spawn → initialize → list tools → teardown. Bounded timeout."""
        total = self._timeouts.connect + self._timeouts.list_tools
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                asyncio.wait_for(self._async_list_tools(), timeout=total)
            )
        except TimeoutError as exc:
            raise MCPTimeoutError(
                f"Server {self._server_name!r}: list_tools timed out after {total:.0f}s"
            ) from exc
        except MCPError:
            raise
        except Exception as exc:
            raise MCPConnectionError(
                f"Server {self._server_name!r}: list_tools failed: {exc}"
            ) from exc
        finally:
            loop.close()

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Spawn → initialize → call tool → teardown. Bounded timeout."""
        total = self._timeouts.connect + self._timeouts.call_tool
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                asyncio.wait_for(self._async_call_tool(tool_name, arguments), timeout=total)
            )
        except TimeoutError as exc:
            raise MCPTimeoutError(
                f"Server {self._server_name!r}: call_tool({tool_name!r}) timed out "
                f"after {total:.0f}s"
            ) from exc
        except MCPError:
            raise
        except Exception as exc:
            raise MCPConnectionError(
                f"Server {self._server_name!r}: call_tool({tool_name!r}) failed: {exc}"
            ) from exc
        finally:
            loop.close()

    async def _async_list_tools(self) -> list[Tool]:
        params = self._make_params()
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.list_tools()
            return list(result.tools)

    async def _async_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> CallToolResult:
        params = self._make_params()
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await session.call_tool(tool_name, arguments)
