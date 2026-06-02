"""§1 + §3 + §4 execution tests.

§1 execute path:
  - TOOL_CALL event → execute_mcp_tool_call → TOOL_RESULT appended
  - Transport error → TOOL_FAILED (fail-closed, orchestrator doesn't crash)
§3 oversized result:
  - Result exceeding MAX_RESULT_BYTES → truncated + output_truncated_at set
  - Result within limit → no truncation
§4 result untrusted:
  - isError=True in call result → TOOL_RESULT with success=False
"""

from __future__ import annotations

import sqlite3
from typing import Any, cast
from unittest.mock import MagicMock

from mcp.types import CallToolResult, TextContent, Tool

from orchestrator.core.event import (
    Event,
    EventType,
    ToolCallMeta,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.mcp.client import MCPSession
from orchestrator.mcp.execution import MAX_RESULT_BYTES, execute_mcp_tool_call
from orchestrator.mcp.transport import MCPConnectionError, MCPTransport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:")
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room_id(store: EventStore) -> Any:

    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


def _make_tool_call_event(room_id: Any, tool_name: str, call_id: str = "tc_1") -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_CALL,
        author="agent:test",
        timestamp=now_ms(),
        content="",
        metadata=ToolCallMeta(
            tool_name=tool_name,
            call_id=call_id,
            params={},
        ).model_dump(),
    )


def _make_session(call_result: CallToolResult | None = None) -> MCPSession:
    """Session with a mocked transport."""
    transport = MagicMock(spec=MCPTransport)
    if call_result is not None:
        transport.call_tool.return_value = call_result
    else:
        transport.call_tool.side_effect = MCPConnectionError("mock server unavailable")

    return MCPSession(
        server_name="filesystem",
        tools=[Tool(name="read_file", inputSchema={"type": "object"})],
        transport=transport,
    )


def _text_result(text: str, *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        isError=is_error,
    )


# ---------------------------------------------------------------------------
# §1 execute path: success → TOOL_RESULT
# ---------------------------------------------------------------------------


def test_execution_success_appends_tool_result() -> None:
    """TOOL_CALL event + successful transport call → TOOL_RESULT appended."""
    store = _make_store()
    room_id = _make_room_id(store)

    tool_name = "mcp__filesystem__read_file"
    tc_event = _make_tool_call_event(room_id, tool_name)
    store.append(tc_event)

    session = _make_session(_text_result("file contents here"))

    execute_mcp_tool_call(
        tool_call_event=tc_event,
        session=session,
        event_store=store,
        room_id=room_id,
        agent_id="test",
    )

    events = store.get_room_events(room_id)
    result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(result_events) == 1

    r = result_events[0]
    assert r.content == "file contents here"
    assert r.metadata["call_id"] == "tc_1"
    assert r.metadata["success"] is True
    assert r.metadata["output_truncated_at"] is None


def test_execution_transport_error_appends_tool_failed() -> None:
    """Transport error → TOOL_FAILED (fail-closed, orchestrator does not crash)."""
    store = _make_store()
    room_id = _make_room_id(store)

    tool_name = "mcp__filesystem__read_file"
    tc_event = _make_tool_call_event(room_id, tool_name)
    store.append(tc_event)

    # Session with failing transport
    session = _make_session(call_result=None)

    execute_mcp_tool_call(
        tool_call_event=tc_event,
        session=session,
        event_store=store,
        room_id=room_id,
        agent_id="test",
    )

    events = store.get_room_events(room_id)
    failed_events = [e for e in events if e.type == EventType.TOOL_FAILED]
    assert len(failed_events) == 1
    assert failed_events[0].metadata["success"] is False

    # No TOOL_RESULT appended
    result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert not result_events


def test_execution_is_error_result_success_false() -> None:
    """isError=True in CallToolResult → TOOL_RESULT success=False."""
    store = _make_store()
    room_id = _make_room_id(store)

    tool_name = "mcp__filesystem__read_file"
    tc_event = _make_tool_call_event(room_id, tool_name)
    store.append(tc_event)

    session = _make_session(_text_result("tool returned an error", is_error=True))

    execute_mcp_tool_call(
        tool_call_event=tc_event,
        session=session,
        event_store=store,
        room_id=room_id,
        agent_id="test",
    )

    events = store.get_room_events(room_id)
    result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(result_events) == 1
    assert result_events[0].metadata["success"] is False


# ---------------------------------------------------------------------------
# §3 oversized result: truncation
# ---------------------------------------------------------------------------


def test_execution_oversized_result_truncated() -> None:
    """Result exceeding MAX_RESULT_BYTES → truncated + output_truncated_at set."""
    store = _make_store()
    room_id = _make_room_id(store)

    tool_name = "mcp__filesystem__read_file"
    tc_event = _make_tool_call_event(room_id, tool_name)
    store.append(tc_event)

    # Generate output just over the cap
    big_text = "x" * (MAX_RESULT_BYTES + 1000)
    session = _make_session(_text_result(big_text))

    execute_mcp_tool_call(
        tool_call_event=tc_event,
        session=session,
        event_store=store,
        room_id=room_id,
        agent_id="test",
    )

    events = store.get_room_events(room_id)
    result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(result_events) == 1

    r = result_events[0]
    assert r.metadata["output_truncated_at"] == MAX_RESULT_BYTES
    assert len(r.content.encode("utf-8")) <= MAX_RESULT_BYTES


def test_execution_within_size_limit_not_truncated() -> None:
    """Result within MAX_RESULT_BYTES → no truncation, output_truncated_at=None."""
    store = _make_store()
    room_id = _make_room_id(store)

    tool_name = "mcp__filesystem__read_file"
    tc_event = _make_tool_call_event(room_id, tool_name)
    store.append(tc_event)

    small_text = "small result"
    session = _make_session(_text_result(small_text))

    execute_mcp_tool_call(
        tool_call_event=tc_event,
        session=session,
        event_store=store,
        room_id=room_id,
        agent_id="test",
    )

    events = store.get_room_events(room_id)
    result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    r = result_events[0]
    assert r.metadata["output_truncated_at"] is None
    assert r.content == small_text


# ---------------------------------------------------------------------------
# §4: bad tool name → TOOL_FAILED (not an mcp__ namespaced name)
# ---------------------------------------------------------------------------


def test_execution_bad_tool_name_fail_closed() -> None:
    """Bad tool name in TOOL_CALL event → TOOL_FAILED (fail-closed)."""
    store = _make_store()
    room_id = _make_room_id(store)

    # Non-namespaced tool name in the TOOL_CALL event
    tc_event = _make_tool_call_event(room_id, "local_tool_not_mcp_namespaced")
    store.append(tc_event)

    session = _make_session(_text_result("should not be called"))

    execute_mcp_tool_call(
        tool_call_event=tc_event,
        session=session,
        event_store=store,
        room_id=room_id,
        agent_id="test",
    )

    events = store.get_room_events(room_id)
    failed_events = [e for e in events if e.type == EventType.TOOL_FAILED]
    assert len(failed_events) == 1

    # Transport should NOT have been called
    cast(MagicMock, session.transport).call_tool.assert_not_called()
