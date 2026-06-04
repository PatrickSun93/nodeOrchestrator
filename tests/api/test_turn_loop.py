"""P4.1-4: Turn-loop acceptance tests (ADR-033 D1/D2/D3).

Covers:
  §1 chain: cooldown=0 agent triggered on tool_result chains read_file →
    search_text → nothing → terminates in one /intent turn.
  §2 zero-new-TOOL_CALL pass exits; dispatch_turn invoked ≤ 1+N times.
  §3 TOOL_FAILED mid-loop continues bounded.
  §4 TOOL_CALL_PENDING (COUNTDOWN) → loop terminates, not executed in-loop.
  §5 state_transition evaluated exactly once/turn.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.agents.schema import (
    Agent,
    AgentAppliesTo,
    EventTypeTrigger,
)
from orchestrator.api.app import MAX_TURN_LOOP_PASSES, AppContext, _make_test_app
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.core.event import EventType, generate_event_id
from orchestrator.core.event_store import EventStore
from orchestrator.llm.types import (
    AgentAutonomyThresholds,
    AgentLLMConfig,
    LLMResponse,
    ModelId,
    ProviderId,
    RequestId,
    ToolCall,
    Usage,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MOCK_MODEL = ModelId("mock-model")
_MOCK_PROVIDER = ProviderId("mock-provider")
_AUTONOMY = AgentAutonomyThresholds(threshold_auto=10, threshold_confirm=3, user_intent_modifier=0)
_LLM_CFG = AgentLLMConfig(default_model=_MOCK_MODEL, autonomy_thresholds=_AUTONOMY)


def _make_store(db_path: str = ":memory:") -> EventStore:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    store = EventStore(conn)
    store.init_schema()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    return store


def _make_agent(
    agent_id: str,
    *,
    cooldown: int = 0,
    trigger_types: list[EventType] | None = None,
    autonomy: AgentAutonomyThresholds | None = None,
) -> Agent:
    """Build a minimal agent for turn-loop tests."""
    if trigger_types is None:
        trigger_types = [EventType.USER_INPUT, EventType.TOOL_RESULT]
    triggers = [EventTypeTrigger(event_type=et) for et in trigger_types]
    return Agent(
        id=agent_id,
        role="tester",
        persona=f"I am {agent_id}",
        speaking_triggers=triggers,  # type: ignore[arg-type]
        cooldown_seconds=cooldown,
        llm_config=AgentLLMConfig(
            default_model=_MOCK_MODEL,
            autonomy_thresholds=autonomy or _AUTONOMY,
        ),
        applies_to=AgentAppliesTo(room_types=["*"], room_states=["*"]),
    )


def _llm_resp(content: str = "ok", tool_calls: list[ToolCall] | None = None) -> LLMResponse:
    return LLMResponse(
        request_id=RequestId(generate_event_id()),
        content=content,
        tool_calls=tool_calls or [],
        model_id_requested=_MOCK_MODEL,
        model_id_used=_MOCK_MODEL,
        provider_id_used=_MOCK_PROVIDER,
        usage=Usage(input_tokens=1, output_tokens=1),
        latency_ms=0,
        finish_reason="stop" if not tool_calls else "tool_use",
    )


def _make_ctx(
    agent: Agent | None = None,
    llm_router: LLMRouterProtocol | None = None,
    tools: dict[str, ToolMeta] | None = None,
    db_path: str = ":memory:",
    reader_db_path: str | None = None,
) -> AppContext:
    writer_store = _make_store(db_path)
    reader_store = _make_store(reader_db_path or db_path)
    writer_exec = ThreadPoolExecutor(max_workers=1)
    reader_exec = ThreadPoolExecutor(max_workers=1)
    bus = RoomEventBus()

    if llm_router is None:
        mock = MagicMock(spec=LLMRouterProtocol)
        mock.call.return_value = _llm_resp()
        llm_router = mock

    return AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=writer_exec,
        reader_executor=reader_exec,
        bus=bus,
        available_agents={agent.id: agent} if agent else {},
        available_skills={},
        regex_registry={},
        tools=tools or {},
        llm_router=llm_router,
    )


def _post_room(client: TestClient, room_type: str = "research") -> str:
    r = client.post("/rooms", json={"type": room_type})
    assert r.status_code == 201
    result: str = r.json()["id"]
    return result


def _post_intent(client: TestClient, room_id: str, content: str = "investigate") -> Any:
    r = client.post(f"/rooms/{room_id}/intent", json={"type": "user_input", "content": content})
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# §1: cooldown=0 agent chains read_file → search_text → nothing → terminates
# ---------------------------------------------------------------------------


def test_turn_loop_chain_two_tool_calls_in_one_turn(tmp_path: Any) -> None:
    """§1: mock LLM returns read_file, then search_text, then nothing.

    One /intent turn drives two re-dispatch passes; both TOOL_RESULTs land
    in-turn; loop terminates on zero-new-TOOL_CALL pass.
    """
    from orchestrator.tools.local import build_local_tool_registry

    # A simple file for read_file to hit.
    test_file = tmp_path / "hello.txt"
    test_file.write_text("hello world\n", encoding="utf-8")

    agent = _make_agent("inv", cooldown=0)

    call_count: list[int] = [0]

    def llm_side_effect(req: Any) -> LLMResponse:
        call_count[0] += 1
        n = call_count[0]
        if n == 1:
            # Pass 0: agent speaks on user_input → requests read_file
            return _llm_resp(
                "reading",
                [ToolCall(id="tc_read", name="read_file", arguments={"path": "hello.txt"})],
            )
        if n == 2:
            # Pass 1 (re-dispatch on TOOL_RESULT): agent speaks → requests search_text
            return _llm_resp(
                "searching",
                [ToolCall(id="tc_search", name="search_text", arguments={"query": "hello"})],
            )
        # Pass 2 (re-dispatch on TOOL_RESULT): agent says nothing → loop terminates
        return _llm_resp("done, no more tools")

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = llm_side_effect

    local_tools = build_local_tool_registry(tmp_path)
    # read_file and search_text are rev-10 AUTO tools
    tools = {
        "read_file": ToolMeta(reversibility=10),
        "search_text": ToolMeta(reversibility=10),
    }

    ctx = _make_ctx(agent=agent, llm_router=router, tools=tools)
    ctx.local_tools = local_tools
    ctx.sandbox_root = tmp_path

    app = _make_test_app(ctx)
    with TestClient(app) as client:
        room_id = _post_room(client)
        _post_intent(client, room_id)

    # Verify both TOOL_RESULTs are present (from read_file and search_text).
    events = ctx.writer_store.get_room_events(room_id)  # type: ignore[arg-type]
    result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(result_events) >= 2, f"Expected ≥2 TOOL_RESULTs in-turn, got {len(result_events)}"

    # dispatch_turn called ≤ 1+N times total.
    assert call_count[0] <= 1 + MAX_TURN_LOOP_PASSES, (
        f"dispatch_turn called {call_count[0]} times, expected ≤ {1 + MAX_TURN_LOOP_PASSES}"
    )


# ---------------------------------------------------------------------------
# §2: zero-new-TOOL_CALL pass exits immediately; dispatch count bounded
# ---------------------------------------------------------------------------


def test_turn_loop_exits_on_zero_tool_calls(tmp_path: Any) -> None:
    """§2: pass with no TOOL_CALL events → loop terminates without re-dispatching."""
    agent = _make_agent("inv", cooldown=0)
    call_count: list[int] = [0]

    def llm_side_effect(req: Any) -> LLMResponse:
        call_count[0] += 1
        if call_count[0] == 1:
            # Pass 0: agent calls read_file.
            return _llm_resp(
                "reading",
                [ToolCall(id="tc_rf", name="read_file", arguments={"path": "f.txt"})],
            )
        # Pass 1 (re-dispatch): agent speaks but no tool calls → should end loop.
        return _llm_resp("done, investigation complete, no more tools")

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = llm_side_effect

    test_file = tmp_path / "f.txt"
    test_file.write_text("content\n", encoding="utf-8")

    from orchestrator.tools.local import build_local_tool_registry

    ctx = _make_ctx(
        agent=agent,
        llm_router=router,
        tools={"read_file": ToolMeta(reversibility=10)},
    )
    ctx.local_tools = build_local_tool_registry(tmp_path)
    ctx.sandbox_root = tmp_path

    app = _make_test_app(ctx)
    with TestClient(app) as client:
        room_id = _post_room(client)
        _post_intent(client, room_id)

    # Should have terminated after pass 1 (2 total calls), not hit N.
    assert call_count[0] == 2, (
        f"Expected exactly 2 dispatch_turn calls; got {call_count[0]}"
    )
    assert call_count[0] <= 1 + MAX_TURN_LOOP_PASSES


# ---------------------------------------------------------------------------
# §3: TOOL_FAILED mid-loop → loop continues up to bound; no crash
# ---------------------------------------------------------------------------


def test_turn_loop_continues_on_tool_failed(tmp_path: Any) -> None:
    """§3: executor raises (TOOL_FAILED) in a pass → loop continues bounded; no hang."""
    agent = _make_agent("inv", cooldown=0)
    call_count: list[int] = [0]

    def llm_side_effect(req: Any) -> LLMResponse:
        call_count[0] += 1
        if call_count[0] == 1:
            # Pass 0: call a non-existent tool → TOOL_FAILED (not_implemented).
            return _llm_resp(
                "trying",
                [ToolCall(id="tc_ghost", name="ghost_tool", arguments={})],
            )
        # After TOOL_FAILED: pass 1 re-dispatches on TOOL_FAILED event;
        # agent returns no tool calls → loop exits.
        return _llm_resp("acknowledged the failure")

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = llm_side_effect

    ctx = _make_ctx(
        agent=agent,
        llm_router=router,
        tools={"ghost_tool": ToolMeta(reversibility=10)},  # classified but not in local_tools
    )
    # ghost_tool not in local_tools → not_implemented → TOOL_FAILED
    ctx.local_tools = {}

    app = _make_test_app(ctx)
    with TestClient(app) as client:
        room_id = _post_room(client)
        response = _post_intent(client, room_id)

    # Request completed without crash.
    assert response is not None
    events = ctx.writer_store.get_room_events(room_id)  # type: ignore[arg-type]
    failed = [e for e in events if e.type == EventType.TOOL_FAILED]
    assert len(failed) >= 1


# ---------------------------------------------------------------------------
# §4: COUNTDOWN call → TOOL_CALL_PENDING → loop terminates; no in-loop execution
# ---------------------------------------------------------------------------


def test_turn_loop_countdown_pending_terminates_loop(tmp_path: Any) -> None:
    """§4: COUNTDOWN tool → TOOL_CALL_PENDING appended, no TOOL_CALL → loop stops.

    The pending call is NOT executed in-loop (D3: loop never blocks on confirm).
    """
    # threshold_auto=10, threshold_confirm=3 → tool at reversibility=5 → COUNTDOWN
    agent = _make_agent(
        "inv",
        cooldown=0,
        autonomy=AgentAutonomyThresholds(
            threshold_auto=10, threshold_confirm=3, user_intent_modifier=0
        ),
    )
    call_count: list[int] = [0]

    def llm_side_effect(req: Any) -> LLMResponse:
        call_count[0] += 1
        if call_count[0] == 1:
            # Pass 0: call a COUNTDOWN-tier tool (reversibility 5 < threshold_auto 10).
            return _llm_resp(
                "propose mutation",
                [ToolCall(id="tc_prop", name="propose_edit", arguments={"content": "x"})],
            )
        # Should NOT reach here — loop must terminate after COUNTDOWN.
        return _llm_resp("unexpected re-dispatch")

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = llm_side_effect

    ctx = _make_ctx(
        agent=agent,
        llm_router=router,
        tools={"propose_edit": ToolMeta(reversibility=5)},
    )

    app = _make_test_app(ctx)
    with TestClient(app) as client:
        room_id = _post_room(client)
        _post_intent(client, room_id)

    events = ctx.writer_store.get_room_events(room_id)  # type: ignore[arg-type]

    # TOOL_CALL_PENDING must be present.
    pending = [e for e in events if e.type == EventType.TOOL_CALL_PENDING]
    assert len(pending) >= 1

    # No TOOL_CALL (AUTO_EXECUTE) must be present for propose_edit.
    tool_calls = [
        e for e in events
        if e.type == EventType.TOOL_CALL
        and e.metadata.get("tool_name") == "propose_edit"
    ]
    assert tool_calls == []

    # Loop terminated after pass 0 (COUNTDOWN → TOOL_CALL_PENDING = zero new TOOL_CALL).
    assert call_count[0] == 1, (
        f"Loop must not re-dispatch after COUNTDOWN; got {call_count[0]} dispatch_turn calls"
    )


# ---------------------------------------------------------------------------
# §5: state_transition evaluated exactly once per turn
# ---------------------------------------------------------------------------


def test_state_machine_runs_once_per_turn() -> None:
    """§5: even with re-dispatch passes, next_room_state runs exactly once."""
    agent = _make_agent("inv", cooldown=0)
    call_count: list[int] = [0]

    def llm_side_effect(req: Any) -> LLMResponse:
        call_count[0] += 1
        if call_count[0] == 1:
            return _llm_resp("t1", [ToolCall(id="tc1", name="get_current_time", arguments={})])
        return _llm_resp("done")

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = llm_side_effect

    from orchestrator.tools.local import build_local_tool_registry

    ctx = _make_ctx(
        agent=agent,
        llm_router=router,
        tools={"get_current_time": ToolMeta(reversibility=10)},
    )
    ctx.local_tools = build_local_tool_registry(ctx.sandbox_root)

    transition_call_count: list[int] = [0]

    original_next = None

    def patched_next_room_state(*args: Any, **kwargs: Any) -> Any:
        transition_call_count[0] += 1
        assert original_next is not None
        return original_next(*args, **kwargs)

    import orchestrator.rooms.runtime as _runtime_mod
    from orchestrator.rooms.state_machine import next_room_state as _original_next

    original_next = _original_next

    app = _make_test_app(ctx)
    with TestClient(app) as client, patch.object(
        _runtime_mod, "next_room_state", side_effect=patched_next_room_state
    ):
        room_id = _post_room(client)
        _post_intent(client, room_id)

    assert transition_call_count[0] == 1, (
        f"next_room_state must run exactly once per turn; ran {transition_call_count[0]} times"
    )


# ---------------------------------------------------------------------------
# §6 (P4.1-5): wall-clock deadline exits loop at pass boundary (D3 condition 4)
# ---------------------------------------------------------------------------


def test_turn_loop_wall_clock_deadline_exits(tmp_path: Any) -> None:
    """§6: when wall-clock deadline fires at pass boundary, loop does not re-dispatch.

    Patches MAX_TURN_LOOP_WALL_CLOCK_S to -1.0 (always expired) so the deadline
    check fires on the first boundary (before pass 1). The in-flight pass 0 is
    not interrupted. ADR-033 D3 condition 4 / D4: absolute wall-clock cap.
    """
    import orchestrator.api.app as _app_mod
    from orchestrator.tools.local import build_local_tool_registry

    test_file = tmp_path / "f.txt"
    test_file.write_text("content\n", encoding="utf-8")

    agent = _make_agent("inv", cooldown=0)
    call_count: list[int] = [0]

    def llm_side_effect(req: Any) -> LLMResponse:
        call_count[0] += 1
        if call_count[0] == 1:
            # Pass 0: call read_file → TOOL_RESULT → would trigger re-dispatch if no deadline.
            return _llm_resp(
                "reading",
                [ToolCall(id="tc_rf2", name="read_file", arguments={"path": "f.txt"})],
            )
        return _llm_resp("unexpected — should not reach re-dispatch")

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = llm_side_effect

    ctx = _make_ctx(
        agent=agent,
        llm_router=router,
        tools={"read_file": ToolMeta(reversibility=10)},
    )
    ctx.local_tools = build_local_tool_registry(tmp_path)
    ctx.sandbox_root = tmp_path

    app = _make_test_app(ctx)
    # Set wall-clock deadline to -1.0 (always expired): the first boundary check
    # will see monotonic() - loop_start >= -1.0 (always True since difference >= 0).
    with TestClient(app) as client, patch.object(_app_mod, "MAX_TURN_LOOP_WALL_CLOCK_S", -1.0):
        room_id = _post_room(client)
        _post_intent(client, room_id)

    # dispatch_turn was called exactly once (pass 0 only); wall-clock fired at boundary.
    assert call_count[0] == 1, (
        f"Wall-clock deadline must prevent re-dispatch; got {call_count[0]} dispatch_turn calls"
    )
    # The in-turn TOOL_RESULT from pass 0's read_file is still present.
    events = ctx.writer_store.get_room_events(room_id)  # type: ignore[arg-type]
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) >= 1
