"""P3.4-C2-1 acceptance tests for tools/executor.py (executor framework + MCP wiring).

§1 MCP execute path:
  - TOOL_CALL(mcp__*) → execute_mcp_tool_call → TOOL_RESULT → interpret → OBSERVATION
  - Session miss (server not in mcp_sessions) → TOOL_FAILED(not_available)
  - Local tool results are NOT interpreted (trusted; no OBSERVATION)

§2 Bounded interpret (R1):
  - When interpret LLM hangs past deadline → TimeoutError caught → no OBSERVATION,
    raw TOOL_RESULT stands, executor returns (writer not blocked indefinitely)

§3 Double-execution guard (full-room scope — R0-B Y1):
  - call_id already has TOOL_RESULT/TOOL_FAILED anywhere in room → skipped
  - Duplicate call_id from a prior turn (not in current window) → still skipped

§4 Per-turn MCP cap (R0-B Y4):
  - >MAX_MCP_CALLS_PER_TURN MCP calls → excess → TOOL_FAILED(turn_mcp_cap_exceeded)
  - Local tools are NOT capped

§5 Per-call isolation:
  - Two TOOL_CALLs, first raises → TOOL_FAILED; second still → TOOL_RESULT

§6 No TOOL_CALL in window → zero executions (t4 behavioral filter)
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    ToolCallMeta,
    ToolCallPendingMeta,
    ToolResultMeta,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.types import LLMRequest, LLMResponse, ModelId, ProviderId, Usage
from orchestrator.mcp.client import MCPSession
from orchestrator.mcp.transport import MCPConnectionError, MCPTransport
from orchestrator.tools.executor import (
    MAX_MCP_CALLS_PER_TURN,
    LocalToolOutput,
    LocalToolRegistry,
    execute_pending_tool_calls,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_MODEL = ModelId("mock-model")
_MOCK_PROVIDER = ProviderId("mock-provider")


def _make_store() -> EventStore:
    # check_same_thread=False required: interpret pool runs on a different thread (ADR-028 D5 R1).
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room(store: EventStore) -> RoomId:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


def _tc_event(room_id: RoomId, tool_name: str, call_id: str = "tc_1") -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_CALL,
        author="agent:tester",
        timestamp=now_ms(),
        content="",
        metadata=ToolCallMeta(
            tool_name=tool_name,
            call_id=call_id,
            params={},
        ).model_dump(),
    )


def _tc_event_params(
    room_id: RoomId, tool_name: str, call_id: str, params: dict[str, Any]
) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_CALL,
        author="agent:tester",
        timestamp=now_ms(),
        content="",
        metadata=ToolCallMeta(
            tool_name=tool_name,
            call_id=call_id,
            params=params,
        ).model_dump(),
    )


def _mcp_session(*, result: str = "ok", error: bool = False) -> MCPSession:
    transport = MagicMock(spec=MCPTransport)
    transport.call_tool.return_value = CallToolResult(
        content=[TextContent(type="text", text=result)],
        isError=error,
    )
    return MCPSession(
        server_name="test_server",
        tools=[Tool(name="do_thing", inputSchema={"type": "object"})],
        transport=transport,
    )


def _mcp_session_fail() -> MCPSession:
    transport = MagicMock(spec=MCPTransport)
    transport.call_tool.side_effect = MCPConnectionError("server unavailable")
    return MCPSession(server_name="test_server", tools=[], transport=transport)


def _mock_llm_router(response: str = "interpretation") -> LLMRouterProtocol:
    mock = MagicMock(spec=LLMRouterProtocol)

    def _call(req: LLMRequest) -> LLMResponse:
        from orchestrator.llm.types import RequestId

        return LLMResponse(
            request_id=RequestId("req_test"),
            content=response,
            model_id_requested=_MOCK_MODEL,
            model_id_used=_MOCK_MODEL,
            provider_id_used=_MOCK_PROVIDER,
            usage=Usage(input_tokens=5, output_tokens=10),
            latency_ms=0,
            finish_reason="stop",
        )

    mock.call.side_effect = _call
    return mock


# ---------------------------------------------------------------------------
# §1 MCP execute path
# ---------------------------------------------------------------------------


def test_mcp_tool_call_appends_tool_result_and_observation() -> None:
    """TOOL_CALL(mcp__test_server__do_thing) → TOOL_RESULT → interpret → OBSERVATION."""
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event(room_id, "mcp__test_server__do_thing")
    store.append(tc)

    session = _mcp_session(result="the result text")

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={"test_server": session},
        local_tools={},
        llm_router=_mock_llm_router("it contains the result text"),
    )

    events = store.get_room_events(room_id)
    tool_results = [e for e in events if e.type == EventType.TOOL_RESULT]
    observations = [e for e in events if e.type == EventType.OBSERVATION]

    assert len(tool_results) == 1
    assert tool_results[0].content == "the result text"
    assert tool_results[0].metadata["call_id"] == "tc_1"
    assert tool_results[0].metadata["success"] is True
    assert len(observations) == 1
    assert "[MCP tool result interpretation]" in observations[0].content


def test_mcp_session_miss_appends_not_available() -> None:
    """mcp__<server>__ where server not in mcp_sessions → TOOL_FAILED(not_available)."""
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event(room_id, "mcp__missing_server__read")
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools={},
        llm_router=_mock_llm_router(),
    )

    events = store.get_room_events(room_id)
    failed = [e for e in events if e.type == EventType.TOOL_FAILED]
    assert len(failed) == 1
    assert failed[0].metadata["error_class"] == "not_available"
    assert not [e for e in events if e.type == EventType.TOOL_RESULT]


def test_local_tool_result_not_interpreted() -> None:
    """Local tool results are trusted — no OBSERVATION appended."""
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event(room_id, "get_current_time")
    store.append(tc)

    local_tools: LocalToolRegistry = {
        "get_current_time": lambda p: LocalToolOutput(content="2026-01-01T00:00:00+00:00"),
    }

    mock_router = _mock_llm_router()
    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=local_tools,
        llm_router=mock_router,
    )

    events = store.get_room_events(room_id)
    assert any(e.type == EventType.TOOL_RESULT for e in events)
    assert not any(e.type == EventType.OBSERVATION for e in events)
    mock_router.call.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# §2 Bounded interpret (R1) — interpret timeout → no OBSERVATION, writer unblocked
# ---------------------------------------------------------------------------


def test_bounded_interpret_timeout_no_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interpret LLM hangs → timeout → no OBSERVATION; raw TOOL_RESULT stands."""
    import orchestrator.tools.executor as _executor_mod

    monkeypatch.setattr(_executor_mod, "INTERPRET_TIMEOUT_S", 0.05)

    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event(room_id, "mcp__test_server__do_thing")
    store.append(tc)
    session = _mcp_session(result="raw result")

    released = threading.Event()

    class HangingRouter:
        def call(self, request: LLMRequest) -> LLMResponse:
            released.wait(timeout=10)
            raise RuntimeError("should not reach after release")

    start = time.monotonic()
    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={"test_server": session},
        local_tools={},
        llm_router=HangingRouter(),
    )
    elapsed = time.monotonic() - start
    released.set()  # release hanging interpret thread

    # Writer was not blocked indefinitely (at most 2x the deadline + generous margin)
    assert elapsed < 1.0, f"executor blocked for {elapsed:.2f}s, should be < 1.0s"

    events = store.get_room_events(room_id)
    tool_results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(tool_results) == 1
    assert tool_results[0].content == "raw result"
    assert not any(e.type == EventType.OBSERVATION for e in events)


def test_interpret_timeout_leaked_thread_no_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaked pool thread that completes after timeout CANNOT write OBSERVATION.

    Y1 structural guarantee: pool task = get_mcp_tool_interpretation (LLM call only);
    event_store.append is called only on the writer thread AFTER future.result() returns.
    A timed-out future whose pool thread eventually completes returns its result into
    the already-cancelled future — the writer never sees it, never appends OBSERVATION.
    (ADR-028 D1/D5 Y1 — single-writer invariant.)
    """
    import orchestrator.tools.executor as _executor_mod

    monkeypatch.setattr(_executor_mod, "INTERPRET_TIMEOUT_S", 0.05)

    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event(room_id, "mcp__test_server__do_thing")
    store.append(tc)
    session = _mcp_session(result="test result")

    thread_completed = threading.Event()

    class SlowRouter:
        def call(self, request: LLMRequest) -> LLMResponse:
            from orchestrator.llm.types import RequestId

            time.sleep(0.3)  # completes well after the 0.05s timeout
            thread_completed.set()
            return LLMResponse(
                request_id=RequestId("req_slow"),
                content="interpretation text",
                model_id_requested=_MOCK_MODEL,
                model_id_used=_MOCK_MODEL,
                provider_id_used=_MOCK_PROVIDER,
                usage=Usage(input_tokens=5, output_tokens=10),
                latency_ms=300,
                finish_reason="stop",
            )

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={"test_server": session},
        local_tools={},
        llm_router=SlowRouter(),
    )

    # Wait for the leaked pool thread to actually complete its LLM call.
    assert thread_completed.wait(timeout=5), "pool thread did not complete within 5s"
    time.sleep(0.05)  # grace period for any hypothetical stray write

    events = store.get_room_events(room_id)
    # TOOL_RESULT present (execute_mcp_tool_call succeeded)
    assert any(e.type == EventType.TOOL_RESULT for e in events)
    # OBSERVATION absent: pool task only returns text; append is on writer thread
    # which did NOT execute append because future timed out before result() returned.
    assert not any(e.type == EventType.OBSERVATION for e in events)


# ---------------------------------------------------------------------------
# §3 Double-execution guard (full-room scope — R0-B Y1)
# ---------------------------------------------------------------------------


def test_double_execution_guard_skips_already_executed_in_window() -> None:
    """call_id that already has a TOOL_RESULT in room → executor skips it."""
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event(room_id, "mcp__test_server__do_thing", "tc_dup")
    store.append(tc)

    existing_result = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_RESULT,
        author="agent:tester",
        timestamp=now_ms(),
        content="already done",
        metadata=ToolResultMeta(call_id="tc_dup", success=True).model_dump(),
    )
    store.append(existing_result)

    session = _mcp_session()
    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={"test_server": session},
        local_tools={},
        llm_router=_mock_llm_router(),
    )

    cast_transport = session.transport
    cast_transport.call_tool.assert_not_called()  # type: ignore[attr-defined]

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert results[0].content == "already done"


def test_double_execution_guard_full_room_scope_prior_turn() -> None:
    """call_id executed in a prior turn (not in current window) → skipped."""
    store = _make_store()
    room_id = _make_room(store)

    prior_tc = _tc_event(room_id, "mcp__test_server__do_thing", "tc_prior")
    store.append(prior_tc)
    prior_result = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_RESULT,
        author="agent:tester",
        timestamp=now_ms(),
        content="prior result",
        metadata=ToolResultMeta(call_id="tc_prior", success=True).model_dump(),
    )
    store.append(prior_result)

    current_tc = _tc_event(room_id, "mcp__test_server__do_thing", "tc_prior")
    store.append(current_tc)

    session = _mcp_session()
    execute_pending_tool_calls(
        window_events=[current_tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={"test_server": session},
        local_tools={},
        llm_router=_mock_llm_router(),
    )

    cast_transport = session.transport
    cast_transport.call_tool.assert_not_called()  # type: ignore[attr-defined]

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert results[0].content == "prior result"


# ---------------------------------------------------------------------------
# §4 Per-turn MCP cap (R0-B Y4)
# ---------------------------------------------------------------------------


def test_per_turn_mcp_cap_exceeded_fails_closed() -> None:
    """MAX_MCP_CALLS_PER_TURN + 1 MCP calls → first N execute, excess → TOOL_FAILED."""
    store = _make_store()
    room_id = _make_room(store)

    n = MAX_MCP_CALLS_PER_TURN + 1
    tc_events: list[Event] = []
    sessions: dict[str, MCPSession] = {}
    for i in range(n):
        call_id = f"tc_{i}"
        tc = _tc_event(room_id, f"mcp__srv{i}__tool", call_id)
        store.append(tc)
        tc_events.append(tc)
        transport = MagicMock(spec=MCPTransport)
        transport.call_tool.return_value = CallToolResult(
            content=[TextContent(type="text", text=f"result_{i}")], isError=False
        )
        sessions[f"srv{i}"] = MCPSession(
            server_name=f"srv{i}",
            tools=[Tool(name="tool", inputSchema={})],
            transport=transport,
        )

    execute_pending_tool_calls(
        window_events=tc_events,
        room_id=room_id,
        event_store=store,
        mcp_sessions=sessions,
        local_tools={},
        llm_router=_mock_llm_router(),
    )

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    failed = [e for e in events if e.type == EventType.TOOL_FAILED]

    assert len(results) == MAX_MCP_CALLS_PER_TURN
    assert len(failed) == 1
    assert failed[0].metadata["error_class"] == "turn_mcp_cap_exceeded"


def test_local_tools_not_subject_to_mcp_cap() -> None:
    """Local tools are not capped (cap applies to MCP only)."""
    store = _make_store()
    room_id = _make_room(store)

    n = MAX_MCP_CALLS_PER_TURN + 5
    tc_events: list[Event] = []
    for i in range(n):
        tc = _tc_event(room_id, "get_current_time", f"tc_local_{i}")
        store.append(tc)
        tc_events.append(tc)

    local_tools: LocalToolRegistry = {
        "get_current_time": lambda p: LocalToolOutput(content="now"),
    }

    execute_pending_tool_calls(
        window_events=tc_events,
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=local_tools,
        llm_router=_mock_llm_router(),
    )

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    failed = [e for e in events if e.type == EventType.TOOL_FAILED]
    assert len(results) == n
    assert not failed


# ---------------------------------------------------------------------------
# §5 Per-call isolation — first call fails, second still executes
# ---------------------------------------------------------------------------


def test_per_call_isolation_first_fails_second_executes() -> None:
    """Two local TOOL_CALLs: first raises → TOOL_FAILED; second still → TOOL_RESULT."""
    store = _make_store()
    room_id = _make_room(store)

    tc_fail = _tc_event(room_id, "always_fail", "tc_fail")
    tc_ok = _tc_event(room_id, "always_ok", "tc_ok")
    store.append(tc_fail)
    store.append(tc_ok)

    def _fail(params: dict[str, Any]) -> LocalToolOutput:
        raise RuntimeError("intentional failure")

    def _ok(params: dict[str, Any]) -> LocalToolOutput:
        return LocalToolOutput(content="ok result")

    local_tools: LocalToolRegistry = {
        "always_fail": _fail,
        "always_ok": _ok,
    }

    execute_pending_tool_calls(
        window_events=[tc_fail, tc_ok],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=local_tools,
        llm_router=_mock_llm_router(),
    )

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    failed = [e for e in events if e.type == EventType.TOOL_FAILED]

    assert len(results) == 1
    assert results[0].content == "ok result"
    assert len(failed) == 1
    assert failed[0].metadata["call_id"] == "tc_fail"


# ---------------------------------------------------------------------------
# §6 No TOOL_CALL in window → zero executions (t4 behavioral)
# ---------------------------------------------------------------------------


def test_no_tool_call_in_window_zero_executions() -> None:
    """No TOOL_CALL events in window → executor makes zero calls, appends nothing."""
    store = _make_store()
    room_id = _make_room(store)

    user_event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.USER_INPUT,
        author="user",
        timestamp=now_ms(),
        content="just chatting",
    )
    store.append(user_event)

    session = _mcp_session()
    execute_pending_tool_calls(
        window_events=[user_event],
        room_id=room_id,
        event_store=store,
        mcp_sessions={"test_server": session},
        local_tools={},
        llm_router=_mock_llm_router(),
    )

    cast_transport = session.transport
    cast_transport.call_tool.assert_not_called()  # type: ignore[attr-defined]

    events = store.get_room_events(room_id)
    assert not any(e.type in (EventType.TOOL_RESULT, EventType.TOOL_FAILED) for e in events)


def test_empty_window_zero_executions() -> None:
    """Empty window → executor makes zero calls, appends nothing."""
    store = _make_store()
    room_id = _make_room(store)

    session = _mcp_session()
    execute_pending_tool_calls(
        window_events=[],
        room_id=room_id,
        event_store=store,
        mcp_sessions={"test_server": session},
        local_tools={},
        llm_router=_mock_llm_router(),
    )

    cast_transport = session.transport
    cast_transport.call_tool.assert_not_called()  # type: ignore[attr-defined]


def test_tool_call_pending_in_window_not_executed() -> None:
    """TOOL_CALL_PENDING events in window are ignored by executor (ADR-030 D1 / B1).

    The executor filters on EventType.TOOL_CALL only; a TOOL_CALL_PENDING event
    (a durable pending record, not yet approved) must NOT be treated as executable.
    """
    store = _make_store()
    room_id = _make_room(store)

    pending_event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_CALL_PENDING,
        author="agent:operator",
        timestamp=now_ms(),
        content="",
        metadata=ToolCallPendingMeta(
            tool_name="apply_edit",
            call_id="call_pending_1",
            params={"path": "/tmp/x"},
            tier="hard_confirm",
            initiating_agent="operator",
        ).model_dump(),
    )
    store.append(pending_event)

    session = _mcp_session()
    execute_pending_tool_calls(
        window_events=[pending_event],
        room_id=room_id,
        event_store=store,
        mcp_sessions={"test_server": session},
        local_tools={},
        llm_router=_mock_llm_router(),
    )

    # No MCP call dispatched
    cast_transport = session.transport
    cast_transport.call_tool.assert_not_called()  # type: ignore[attr-defined]

    # No TOOL_RESULT or TOOL_FAILED appended
    events = store.get_room_events(room_id)
    assert not any(e.type in (EventType.TOOL_RESULT, EventType.TOOL_FAILED) for e in events)

    events = store.get_room_events(room_id)
    assert not any(e.type in (EventType.TOOL_RESULT, EventType.TOOL_FAILED) for e in events)


# ---------------------------------------------------------------------------
# §8 Network tool (B4-4): web_fetch TOOL_CALL → TOOL_RESULT end-to-end through executor
# ---------------------------------------------------------------------------


def test_web_fetch_tool_call_reaches_tool_result() -> None:
    """web_fetch TOOL_CALL (mocked transport) → TOOL_RESULT through execute_pending_tool_calls.

    Integration test: confirms the network registry wiring lands the tool as a normal
    local-tool TOOL_RESULT, not TOOL_FAILED.  The _NetworkToolFn is used directly
    (not through api/app.py) to avoid HTTP egress.
    """
    from unittest.mock import MagicMock, patch

    from orchestrator.tools.network_tools import _NetworkToolFn, build_network_tool_registry

    store = _make_store()
    room_id = _make_room(store)

    # Mock build_ssrf_client so web_fetch doesn't egress.
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.url = "https://example.com/"
    mock_resp.iter_bytes.return_value = iter([b"hello from example"])

    mock_client = MagicMock()
    mock_client.build_request.return_value = MagicMock()
    mock_client.send.return_value = mock_resp

    registry = build_network_tool_registry()
    tc = _tc_event_params(room_id, "web_fetch", "wf_1", {"url": "https://example.com/"})
    store.append(tc)

    # Patch build_ssrf_client while the tool executes (closure looks up name at call time).
    with patch("orchestrator.tools.network_tools.build_ssrf_client", return_value=mock_client):
        execute_pending_tool_calls(
            window_events=[tc],
            room_id=room_id,
            event_store=store,
            mcp_sessions={},
            local_tools=registry,
            llm_router=_mock_llm_router(),
        )

    events = store.get_room_events(room_id)
    result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(result_events) == 1, "web_fetch TOOL_CALL should produce exactly one TOOL_RESULT"
    assert "hello from example" in result_events[0].content

    # Confirm web_fetch fn carries the network tool marker
    web_fetch_fn = registry["web_fetch"]
    assert isinstance(web_fetch_fn, _NetworkToolFn)
    assert getattr(web_fetch_fn, "_is_network_tool", False) is True


# ---------------------------------------------------------------------------
# §9 Per-turn network cap (B4-5): MAX_NETWORK_CALLS_PER_TURN + independence from subprocess cap
# ---------------------------------------------------------------------------


def test_network_cap_exceeded() -> None:
    """Network calls beyond MAX_NETWORK_CALLS_PER_TURN → TOOL_FAILED(turn_network_cap_exceeded)."""
    from orchestrator.tools.executor import MAX_NETWORK_CALLS_PER_TURN
    from orchestrator.tools.network_tools import _NetworkToolFn

    store = _make_store()
    room_id = _make_room(store)

    call_count = MAX_NETWORK_CALLS_PER_TURN + 1

    # Build a simple _NetworkToolFn that always succeeds.
    dummy_fn = _NetworkToolFn(lambda params: LocalToolOutput("net result"))
    local_tools: LocalToolRegistry = {"web_fetch": dummy_fn}

    tc_events: list[Event] = []
    for i in range(call_count):
        tc = _tc_event_params(room_id, "web_fetch", f"net_{i}", {"url": "https://example.com/"})
        store.append(tc)
        tc_events.append(tc)

    execute_pending_tool_calls(
        window_events=tc_events,
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=local_tools,
        llm_router=_mock_llm_router(),
    )

    all_events = store.get_room_events(room_id)
    results = [e for e in all_events if e.type == EventType.TOOL_RESULT]
    failures = [e for e in all_events if e.type == EventType.TOOL_FAILED]

    assert len(results) == MAX_NETWORK_CALLS_PER_TURN
    assert len(failures) == 1
    assert "turn_network_cap_exceeded" in failures[0].content


def test_subprocess_and_network_caps_are_independent() -> None:
    """10 subprocess + 10 network calls in one pass — both allowed (separate caps)."""
    from orchestrator.tools.executor import (
        MAX_NETWORK_CALLS_PER_TURN,
        MAX_SUBPROCESS_CALLS_PER_TURN,
    )
    from orchestrator.tools.network_tools import _NetworkToolFn
    from orchestrator.tools.subprocess_tools import _SubprocessToolFn

    store = _make_store()
    room_id = _make_room(store)

    subprocess_fn = _SubprocessToolFn(lambda params: LocalToolOutput("sub result"))
    network_fn = _NetworkToolFn(lambda params: LocalToolOutput("net result"))
    local_tools: LocalToolRegistry = {
        "run_tests": subprocess_fn,
        "web_fetch": network_fn,
    }

    tc_events: list[Event] = []
    for i in range(MAX_SUBPROCESS_CALLS_PER_TURN):
        tc = _tc_event_params(room_id, "run_tests", f"sub_{i}", {})
        store.append(tc)
        tc_events.append(tc)
    for i in range(MAX_NETWORK_CALLS_PER_TURN):
        tc = _tc_event_params(room_id, "web_fetch", f"net_{i}", {"url": "https://example.com/"})
        store.append(tc)
        tc_events.append(tc)

    execute_pending_tool_calls(
        window_events=tc_events,
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=local_tools,
        llm_router=_mock_llm_router(),
    )

    all_events = store.get_room_events(room_id)
    results = [e for e in all_events if e.type == EventType.TOOL_RESULT]
    failures = [e for e in all_events if e.type == EventType.TOOL_FAILED]

    # All 20 calls succeed (10 sub + 10 net; caps are independent)
    assert len(failures) == 0, f"Expected 0 failures but got {[f.content for f in failures]}"
    assert len(results) == MAX_SUBPROCESS_CALLS_PER_TURN + MAX_NETWORK_CALLS_PER_TURN
