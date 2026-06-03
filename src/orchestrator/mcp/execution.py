"""MCP execution: run approved tool calls downstream of the TOOL_CALL gate event.

execute_mcp_tool_call() contacts the MCP server ONLY for tool calls where a
TOOL_CALL event was appended by process_tool_calls (i.e., AUTO_EXECUTE tier).
On success: appends TOOL_RESULT with size-limited, untrusted-framed output.
On any failure (timeout, crash, malformed): appends TOOL_FAILED (fail-closed).

The TOOL_CALL event IS the gate's approval record (ADR-027 D6, HR#4).
No LLM calls here. No routing / judgment (HR#6).
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent

from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    ToolResultMeta,
    build_author,
    generate_event_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.mcp.adapter import to_mcp_call
from orchestrator.mcp.client import MCPSession, call_tool
from orchestrator.mcp.transport import MCPError

_log = logging.getLogger("orchestrator.mcp.execution")

# Untrusted result size cap (bytes). Over-cap: truncate + set output_truncated_at.
# (ADR-027 D4 / HR#9 — size-limit the untrusted result.)
MAX_RESULT_BYTES: int = 65_536  # 64 KiB


def execute_mcp_tool_call(
    *,
    tool_call_event: Event,
    session: MCPSession,
    event_store: EventStore,
    room_id: RoomId,
    agent_id: str,
) -> None:
    """Execute one MCP tool call: TOOL_CALL event → TOOL_RESULT or TOOL_FAILED.

    Call this only for TOOL_CALL events where tool_name starts with "mcp__".
    The TOOL_CALL event IS the gate's approval record; never call this without one.

    Args:
        tool_call_event: The TOOL_CALL event (gate approval record).
        session: Active MCPSession with transport for the server.
        event_store: Event store for appending results.
        room_id: Room the call belongs to.
        agent_id: Initiating agent id (for event authorship).
    """
    if tool_call_event.type != EventType.TOOL_CALL:
        raise ValueError(
            f"execute_mcp_tool_call requires a TOOL_CALL event, got {tool_call_event.type!r}"
        )

    meta: dict[str, Any] = tool_call_event.metadata
    tool_name: str = str(meta.get("tool_name", ""))
    call_id: str = str(meta.get("call_id", ""))
    params: dict[str, Any] = dict(meta.get("params", {}))
    author = build_author(agent_id)

    try:
        _server_name, mcp_tool_name = to_mcp_call(tool_name)
    except Exception as exc:
        _log.warning("mcp execute: bad tool name %r: %s", tool_name, exc)
        _append_failed(event_store, room_id, call_id, author, f"bad_tool_name: {exc}")
        return

    try:
        result = call_tool(session, mcp_tool_name, params)
    except MCPError as exc:
        _log.warning("mcp execute: %s failed: %s", tool_name, exc)
        _append_failed(event_store, room_id, call_id, author, str(exc))
        return
    except Exception as exc:
        _log.exception("mcp execute: unexpected error for %s", tool_name)
        _append_failed(event_store, room_id, call_id, author, f"unexpected: {exc}")
        return

    # Collect text content from result (untrusted external data, HR#9).
    output_parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            output_parts.append(block.text)
    raw_output = "\n".join(output_parts)

    # Size-limit (HR#9 — untrusted result, cap before storing).
    truncated_at: int | None = None
    output_bytes = raw_output.encode("utf-8")
    if len(output_bytes) > MAX_RESULT_BYTES:
        raw_output = output_bytes[:MAX_RESULT_BYTES].decode("utf-8", errors="replace")
        truncated_at = MAX_RESULT_BYTES
        _log.info("mcp execute: %s result truncated at %d bytes", tool_name, MAX_RESULT_BYTES)

    event_store.append(
        Event(
            id=generate_event_id(),
            room_id=room_id,
            type=EventType.TOOL_RESULT,
            author=author,
            timestamp=now_ms(),
            content=raw_output,
            metadata=ToolResultMeta(
                call_id=call_id,
                success=not result.isError,
                output_truncated_at=truncated_at,
            ).model_dump(),
        )
    )


def _append_failed(
    event_store: EventStore,
    room_id: RoomId,
    call_id: str,
    author: str,
    reason: str,
) -> None:
    event_store.append(
        Event(
            id=generate_event_id(),
            room_id=room_id,
            type=EventType.TOOL_FAILED,
            author=author,
            timestamp=now_ms(),
            content=f"mcp_tool_failed: {reason}",
            metadata=ToolResultMeta(
                call_id=call_id,
                success=False,
                error_class="MCPError",
            ).model_dump(),
        )
    )
