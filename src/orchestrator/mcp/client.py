"""MCPSession: connect + list tools + call tools (sync API over MCPTransport).

Public API:
  connect(server_name, server_cfg) → MCPSession   (discover tools)
  list_tools(session)              → list[Tool]
  call_tool(session, name, args)   → CallToolResult

ADR-027 D1. No routing / judgment here (HR#6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp.types import CallToolResult, Tool

from orchestrator.mcp.config import MCPServerConfig, MCPTimeouts
from orchestrator.mcp.transport import MCPTransport


@dataclass
class MCPSession:
    """A discovered-and-ready MCP server session.

    ``tools`` is populated at connect time (list_tools discovery).
    ``transport`` is used by execution to call tools post-gate-approval.
    """

    server_name: str
    tools: list[Tool]
    transport: MCPTransport = field(repr=False)


def connect(
    server_name: str,
    server_cfg: MCPServerConfig,
    timeouts: MCPTimeouts | None = None,
) -> MCPSession:
    """Connect to an MCP server: spawn → initialize → discover tools.

    Raises MCPTimeoutError if the server doesn't respond in time.
    Raises MCPConnectionError on any transport failure.
    """
    transport = MCPTransport(server_name, server_cfg, timeouts)
    tools = transport.list_tools()
    return MCPSession(server_name=server_name, tools=tools, transport=transport)


def list_tools(session: MCPSession) -> list[Tool]:
    """Return the tools discovered at connect time (no new subprocess spawn)."""
    return session.tools


def call_tool(
    session: MCPSession,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> CallToolResult:
    """Execute a tool call via the session's transport.

    Raises MCPTimeoutError on timeout (fail-closed).
    Raises MCPConnectionError on transport failure.
    """
    return session.transport.call_tool(tool_name, arguments or {})
