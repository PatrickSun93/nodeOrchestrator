"""Transport-agnostic asyncio.wait_for sync bridge (ADR-031 D2-a).

Reused by:
  mcp/transport.py — stdio AND remote streamable-http paths (R0-A G1 seam split).

Provides the MCPError exception hierarchy and run_sync(), which executes an
async coroutine on a fresh event loop under a bounded asyncio.wait_for timeout.
Transport variants (stdio subprocess, remote HTTP) are independent callers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


class MCPError(Exception):
    """Base class for MCP transport errors."""


class MCPTimeoutError(MCPError):
    """SDK call timed out; subprocess killed (stdio) or connection closed (remote)."""


class MCPConnectionError(MCPError):
    """Failed to connect or call the MCP server."""


def run_sync[T](
    coro: Coroutine[Any, Any, T],
    *,
    timeout: float,
    timeout_msg: str,
    error_msg_prefix: str,
) -> T:
    """Run an async coroutine synchronously with a bounded asyncio.wait_for timeout.

    Creates a fresh event loop per call (each call_tool/list_tools is isolated).
    Re-raises MCPError subtypes directly. Wraps all other exceptions as
    MCPConnectionError.

    Args:
        coro: Coroutine to run.
        timeout: Total timeout in seconds.
        timeout_msg: MCPTimeoutError message on timeout.
        error_msg_prefix: Prefix for MCPConnectionError messages (exc appended).
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
    except TimeoutError as exc:
        raise MCPTimeoutError(timeout_msg) from exc
    except MCPError:
        raise
    except Exception as exc:
        raise MCPConnectionError(f"{error_msg_prefix}: {exc}") from exc
    finally:
        loop.close()
