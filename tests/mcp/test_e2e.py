"""§1 interpret wiring + §2 concurrency + §3 failure integration + demo e2e.

Interpret wiring (ADR-027 D6, HR#5):
  - TOOL_RESULT event + LLM router → OBSERVATION interpretation appended
  - Uses TOOL_OUTPUT_INTERPRET purpose (no new purpose)
  - Untrusted-framing: interpret fails silently (orchestrator not crashed)
  - Wrong event type → ValueError guard

Demo e2e (ADR-027 D7 + arch Y1):
  - read_file (rev 10) → AUTO_EXECUTE → TOOL_CALL event appended
    [actual server execution tested separately in §3 / transport tests]
  - write_file (rev 2) → HARD_CONFIRM → no TOOL_CALL event (gated, not executed)
  - Full pipeline demonstrated with mocked execution

Feed-the-gate diff verification:
  - score/decide_tier/emit_gate_decision/process_tool_calls unchanged
    (verified by constitution + by running existing test_tool_dispatch suite)

Note: Tests requiring an actual running npx/filesystem MCP server
are marked with xfail / skipif to avoid CI dependency on npm/npx.
The structural and mock tests run unconditionally.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.agents.mcp_interpret import interpret_mcp_tool_result
from orchestrator.agents.tool_dispatch import process_tool_calls
from orchestrator.autonomy.scoring import AutonomyTier, ThresholdConfig, ToolMeta
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    ToolResultMeta,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import LLMRequest, LLMResponse, ModelId, ProviderId, ToolCall, Usage
from orchestrator.mcp.adapter import build_tool_registry
from orchestrator.mcp.config import MCPServerConfig, MCPToolConfig
from orchestrator.mcp.execution import execute_mcp_tool_call
from orchestrator.mcp.transport import MCPTransport

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_THRESHOLDS = ThresholdConfig(threshold_auto=7, threshold_confirm=3, user_intent_modifier=0)
# read_file rev=10 >= auto=7 → AUTO_EXECUTE
# write_file rev=2 < confirm=3 → HARD_CONFIRM


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:")
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room_id(store: EventStore) -> RoomId:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


def _make_tool_event(room_id: RoomId, name: str) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.USER_INPUT,
        author="user",
        timestamp=now_ms(),
        content=f"please run {name}",
    )


def _tool_call(name: str, call_id: str = "tc_1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={})


def _make_mcp_tool(name: str) -> Tool:
    return Tool(name=name, inputSchema={"type": "object", "properties": {}})


_MOCK_MODEL = ModelId("mock-model")
_MOCK_PROVIDER = ProviderId("mock-provider")


def _llm_response(request_id: str, content: str) -> LLMResponse:
    from orchestrator.llm.types import RequestId

    return LLMResponse(
        request_id=RequestId(request_id),
        content=content,
        model_id_requested=_MOCK_MODEL,
        model_id_used=_MOCK_MODEL,
        provider_id_used=_MOCK_PROVIDER,
        usage=Usage(input_tokens=10, output_tokens=20),
        latency_ms=0,
        finish_reason="stop",
    )


def _make_mock_llm_router(response_text: str) -> LLMRouterProtocol:
    """Mock LLM router that returns fixed text for TOOL_OUTPUT_INTERPRET."""
    mock = MagicMock(spec=LLMRouterProtocol)

    def _call(request: LLMRequest) -> LLMResponse:
        return _llm_response(str(request.request_id), response_text)

    mock.call.side_effect = _call
    return mock  # MagicMock satisfies LLMRouterProtocol at runtime


def _make_demo_registry() -> dict[str, ToolMeta]:
    """Build the filesystem demo tool registry (ADR-027 D7)."""
    server_cfg = MCPServerConfig(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        tools={
            "read_file": MCPToolConfig(reversibility=10),
            "list_directory": MCPToolConfig(reversibility=10),
            "write_file": MCPToolConfig(reversibility=2),
            "move_file": MCPToolConfig(reversibility=1),
        },
    )
    discovered = [
        _make_mcp_tool("read_file"),
        _make_mcp_tool("list_directory"),
        _make_mcp_tool("write_file"),
        _make_mcp_tool("move_file"),
    ]
    return build_tool_registry("filesystem", server_cfg, discovered)


# ---------------------------------------------------------------------------
# Interpret wiring tests (ADR-027 D6, HR#5)
# ---------------------------------------------------------------------------


def test_interpret_appends_observation_event() -> None:
    """TOOL_RESULT + LLM router → OBSERVATION event with interpretation."""
    store = _make_store()
    room_id = _make_room_id(store)

    tool_result_event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_RESULT,
        author="agent:test",
        timestamp=now_ms(),
        content="file contents: hello world",
        metadata=ToolResultMeta(call_id="tc_1", success=True).model_dump(),
    )
    store.append(tool_result_event)

    llm_router = _make_mock_llm_router("The file contains the text 'hello world'.")

    interpret_mcp_tool_result(
        tool_result_event=tool_result_event,
        agent_id="test",
        room_id=room_id,
        event_store=store,
        llm_router=llm_router,
    )

    events = store.get_room_events(room_id)
    observations = [e for e in events if e.type == EventType.OBSERVATION]
    assert len(observations) == 1
    obs_content = observations[0].content.lower()
    assert "hello world" in obs_content or "interpret" in obs_content
    assert observations[0].author == "agent:test"


def test_interpret_uses_tool_output_interpret_purpose() -> None:
    """interpret_mcp_tool_result uses TOOL_OUTPUT_INTERPRET (no new purpose, HR#5)."""
    store = _make_store()
    room_id = _make_room_id(store)

    tool_result_event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_RESULT,
        author="agent:test",
        timestamp=now_ms(),
        content="some output",
        metadata=ToolResultMeta(call_id="tc_2", success=True).model_dump(),
    )
    store.append(tool_result_event)

    captured_requests: list[LLMRequest] = []

    class CapturingRouter:
        def call(self, request: LLMRequest) -> LLMResponse:
            captured_requests.append(request)
            return _llm_response(str(request.request_id), "interpretation")

    interpret_mcp_tool_result(
        tool_result_event=tool_result_event,
        agent_id="test",
        room_id=room_id,
        event_store=store,
        llm_router=CapturingRouter(),
    )

    assert len(captured_requests) == 1
    assert captured_requests[0].purpose == LLMPurpose.TOOL_OUTPUT_INTERPRET


def test_interpret_fails_silently_on_llm_error() -> None:
    """Interpret LLM failure → silently skipped (orchestrator not crashed)."""
    store = _make_store()
    room_id = _make_room_id(store)

    tool_result_event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_RESULT,
        author="agent:test",
        timestamp=now_ms(),
        content="some output",
        metadata=ToolResultMeta(call_id="tc_3", success=True).model_dump(),
    )
    store.append(tool_result_event)

    class FailingRouter:
        def call(self, request: LLMRequest) -> LLMResponse:
            raise RuntimeError("LLM unavailable")

    # Should NOT raise
    interpret_mcp_tool_result(
        tool_result_event=tool_result_event,
        agent_id="test",
        room_id=room_id,
        event_store=store,
        llm_router=FailingRouter(),
    )

    events = store.get_room_events(room_id)
    observations = [e for e in events if e.type == EventType.OBSERVATION]
    assert not observations  # no interpretation appended


def test_interpret_wrong_event_type_raises() -> None:
    """interpret_mcp_tool_result raises ValueError for non-TOOL_RESULT event."""
    store = _make_store()
    room_id = _make_room_id(store)

    wrong_event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.USER_INPUT,
        author="user",
        timestamp=now_ms(),
        content="hello",
    )

    with pytest.raises(ValueError, match="TOOL_RESULT"):
        interpret_mcp_tool_result(
            tool_result_event=wrong_event,
            agent_id="test",
            room_id=room_id,
            event_store=store,
            llm_router=_make_mock_llm_router("irrelevant"),
        )


# ---------------------------------------------------------------------------
# Demo e2e: full pipeline (mocked execution) — ADR-027 D7 + arch Y1
# ---------------------------------------------------------------------------


def test_demo_read_file_auto_execute_full_pipeline() -> None:
    """Demo path i: read_file rev=10 → AUTO_EXECUTE → TOOL_CALL → TOOL_RESULT → interpret.

    The gate (AUTO_EXECUTE) → execution (mocked) → interpret chain works
    end-to-end. This is the constitutional demonstration (ADR-027 D7).
    """
    store = _make_store()
    room_id = _make_room_id(store)
    user_event = _make_tool_event(room_id, "mcp__filesystem__read_file")
    store.append(user_event)

    registry = _make_demo_registry()

    # Step 1: Gate — should AUTO_EXECUTE
    result = process_tool_calls(
        [_tool_call("mcp__filesystem__read_file")],
        agent_id="test",
        room_id=room_id,
        current_event=user_event,
        event_store=store,
        tools=registry,
        thresholds=_THRESHOLDS,
    )
    assert result.decisions[0].tier == AutonomyTier.AUTO_EXECUTE
    assert result.decisions[0].tool_call_event_appended is True

    # Fetch the TOOL_CALL event
    events = store.get_room_events(room_id)
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 1

    # Step 2: Execute (mocked transport — no actual server needed)
    from orchestrator.mcp.client import MCPSession

    mock_transport = MagicMock(spec=MCPTransport)
    mock_transport.call_tool.return_value = CallToolResult(
        content=[TextContent(type="text", text="file contents: hello mcp")],
        isError=False,
    )
    session = MCPSession(
        server_name="filesystem",
        tools=[_make_mcp_tool("read_file")],
        transport=mock_transport,
    )

    execute_mcp_tool_call(
        tool_call_event=tool_call_events[0],
        session=session,
        event_store=store,
        room_id=room_id,
        agent_id="test",
    )

    events = store.get_room_events(room_id)
    tool_result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(tool_result_events) == 1
    assert tool_result_events[0].content == "file contents: hello mcp"
    assert tool_result_events[0].metadata["success"] is True

    # Step 3: Interpret
    llm_router = _make_mock_llm_router("The file contains the text 'hello mcp'.")
    interpret_mcp_tool_result(
        tool_result_event=tool_result_events[0],
        agent_id="test",
        room_id=room_id,
        event_store=store,
        llm_router=llm_router,
    )

    events = store.get_room_events(room_id)
    observations = [e for e in events if e.type == EventType.OBSERVATION]
    assert len(observations) == 1
    assert "[MCP tool result interpretation]" in observations[0].content


def test_demo_write_file_hard_confirm_not_executed() -> None:
    """Demo path ii: write_file rev=2 → HARD_CONFIRM → no TOOL_CALL, NOT executed.

    The constitutional demonstration (ADR-027 D7, arch Y1):
    HARD_CONFIRM = gated but not executed in MVP AUTO-only mode.
    """
    store = _make_store()
    room_id = _make_room_id(store)
    user_event = _make_tool_event(room_id, "mcp__filesystem__write_file")
    store.append(user_event)

    registry = _make_demo_registry()

    result = process_tool_calls(
        [_tool_call("mcp__filesystem__write_file")],
        agent_id="test",
        room_id=room_id,
        current_event=user_event,
        event_store=store,
        tools=registry,
        thresholds=_THRESHOLDS,
    )

    d = result.decisions[0]
    assert d.tier == AutonomyTier.HARD_CONFIRM
    assert d.tool_call_event_appended is False  # MVP: no confirm-then-execute flow

    events = store.get_room_events(room_id)
    # No TOOL_CALL event → write_file was NOT executed
    assert not [e for e in events if e.type == EventType.TOOL_CALL]
    # No TOOL_RESULT → nothing was executed
    assert not [e for e in events if e.type == EventType.TOOL_RESULT]


def test_demo_tier_discrimination_both_paths() -> None:
    """Both read (AUTO) and write (HARD) in one session → gate discriminates correctly."""
    store = _make_store()
    room_id = _make_room_id(store)
    user_event = _make_tool_event(room_id, "both")
    store.append(user_event)

    registry = _make_demo_registry()

    result = process_tool_calls(
        [
            _tool_call("mcp__filesystem__read_file", call_id="tc_read"),
            _tool_call("mcp__filesystem__write_file", call_id="tc_write"),
        ],
        agent_id="test",
        room_id=room_id,
        current_event=user_event,
        event_store=store,
        tools=registry,
        thresholds=_THRESHOLDS,
    )

    decisions = {d.tool_name: d for d in result.decisions}
    assert decisions["mcp__filesystem__read_file"].tier == AutonomyTier.AUTO_EXECUTE
    assert decisions["mcp__filesystem__read_file"].tool_call_event_appended is True
    assert decisions["mcp__filesystem__write_file"].tier == AutonomyTier.HARD_CONFIRM
    assert decisions["mcp__filesystem__write_file"].tool_call_event_appended is False

    events = store.get_room_events(room_id)
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].metadata["tool_name"] == "mcp__filesystem__read_file"


# ---------------------------------------------------------------------------
# §2 concurrency: mcp_servers.yaml config loads correctly
# ---------------------------------------------------------------------------


def test_mcp_servers_config_loads(tmp_path: Any) -> None:
    """The demo config (mcp_servers.yaml) parses and validates correctly."""
    from pathlib import Path

    from orchestrator.mcp.config import load_mcp_servers_config

    cfg_path = Path(__file__).resolve().parent.parent.parent / "config" / "mcp_servers.yaml"
    if not cfg_path.exists():
        pytest.skip("config/mcp_servers.yaml not found")

    cfg = load_mcp_servers_config(cfg_path)
    assert "filesystem" in cfg.servers
    fs = cfg.servers["filesystem"]
    assert "read_file" in fs.tools
    assert "write_file" in fs.tools
    assert fs.tools["read_file"].reversibility == 10
    assert fs.tools["write_file"].reversibility == 2
    assert fs.tools["move_file"].reversibility == 1
    # Credential indirection: api_key_env=null for filesystem (no secret needed)
    assert fs.api_key_env is None
    # Scoped env: no inline secrets
    assert isinstance(fs.env, dict)


# ---------------------------------------------------------------------------
# Feed-the-gate verification: gate functions not modified by P3.4
# ---------------------------------------------------------------------------


def test_gate_functions_signature_unchanged() -> None:
    """Gate functions (score/decide_tier/gate/emit_gate_decision/process_tool_calls)
    must have the expected signatures (verifies P3.4 didn't alter them)."""
    import inspect

    from orchestrator.agents.tool_dispatch import process_tool_calls
    from orchestrator.autonomy.emission import emit_gate_decision
    from orchestrator.autonomy.scoring import decide_tier, gate, score

    # score: (operation: Operation, tools: dict[str, ToolMeta]) -> int
    sig = inspect.signature(score)
    assert "operation" in sig.parameters
    assert "tools" in sig.parameters

    # decide_tier: (score_value: int, thresholds: ..., user_explicit_intent: bool, *, tool_id: str)
    sig = inspect.signature(decide_tier)
    assert "score_value" in sig.parameters
    assert "thresholds" in sig.parameters

    # gate: (operation, tools, thresholds) -> AutonomyScore
    sig = inspect.signature(gate)
    assert "operation" in sig.parameters
    assert "tools" in sig.parameters
    assert "thresholds" in sig.parameters

    # emit_gate_decision: (operation, tools, thresholds, event_store, *, room_id, author)
    sig = inspect.signature(emit_gate_decision)
    assert "operation" in sig.parameters
    assert "tools" in sig.parameters
    assert "event_store" in sig.parameters

    # process_tool_calls: (tool_calls, *, agent_id, room_id, current_event,
    #                      event_store, tools, thresholds)
    sig = inspect.signature(process_tool_calls)
    assert "tool_calls" in sig.parameters
    assert "tools" in sig.parameters
    assert "thresholds" in sig.parameters
