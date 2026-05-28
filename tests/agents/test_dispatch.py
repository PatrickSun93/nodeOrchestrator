"""Tests for src/orchestrator/agents/dispatch.py.

Coverage standard:
  §2 snapshot-semantics test: prober speaks first; skeptic's should_agent_speak
     receives a snapshot that does NOT include prober's utterance within the turn.
  §3 LLM exception: log + skip + continue (ADR-011 D7).
  §3 event_store.append failure aborts turn (ADR-011 D7-b).
  §1 cross-module source ≠ sink: utterance.author == build_author(agent_id).
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.agents.dispatch import LLMRouterProtocol, dispatch_turn
from orchestrator.agents.schema import Agent
from orchestrator.core.event import (
    Event,
    EventType,
    build_author,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import (
    AgentAutonomyThresholds,
    AgentLLMConfig,
    LLMRequest,
    LLMResponse,
    ModelId,
    ProviderId,
    Usage,
    generate_request_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTONOMY = AgentAutonomyThresholds(
    threshold_auto=8,
    threshold_confirm=4,
    user_intent_modifier=2,
)
_LLM = AgentLLMConfig(
    default_model=ModelId("m1"),
    autonomy_thresholds=_AUTONOMY,
)
_PROVIDER = ProviderId("p1")


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:")
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room(store: EventStore) -> Room:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room


def _make_event(
    room_id: Any,
    *,
    type: EventType = EventType.USER_INPUT,
    content: str = "hello",
    author: str = "user",
) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=type,
        author=author,
        timestamp=now_ms(),
        content=content,
    )


def _agent(
    agent_id: str,
    *,
    trigger_type: EventType = EventType.USER_INPUT,
) -> Agent:
    from orchestrator.agents.schema import EventTypeTrigger

    return Agent(
        id=agent_id,
        role="r",
        persona=f"persona of {agent_id}",
        llm_config=_LLM,
        speaking_triggers=[EventTypeTrigger(event_type=trigger_type)],
    )


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        request_id=generate_request_id(),
        content=content,
        model_id_requested=ModelId("m1"),
        model_id_used=ModelId("m1"),
        provider_id_used=_PROVIDER,
        usage=Usage(input_tokens=10, output_tokens=20),
        latency_ms=100,
        finish_reason="stop",
    )


def _mock_router(*contents: str) -> MagicMock:
    """Build a mock router returning each content in sequence."""
    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = [_llm_response(c) for c in contents]
    return router


# ---------------------------------------------------------------------------
# 1. Happy-path: single agent speaks
# ---------------------------------------------------------------------------


def test_dispatch_happy_path_one_agent_speaks() -> None:
    store = _make_store()
    room = _make_room(store)
    agent = _agent("alpha", trigger_type=EventType.USER_INPUT)
    current = _make_event(room.id, type=EventType.USER_INPUT, content="question")
    store.append(current)

    router = _mock_router("alpha says hi")
    result = dispatch_turn(
        {"alpha": agent},
        room,
        current,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools={},
    )

    assert result.total_asked == 1
    assert len(result.utterances) == 1
    assert result.failed_agents == []
    assert result.utterances[0].content == "alpha says hi"
    assert result.utterances[0].type == EventType.UTTERANCE
    assert result.utterances[0].author == build_author("alpha")
    assert result.utterances[0].parent_id == current.id


# ---------------------------------------------------------------------------
# 2. Happy-path: two agents, alphabetical order
# ---------------------------------------------------------------------------


def test_dispatch_two_agents_alphabetical_order() -> None:
    store = _make_store()
    room = _make_room(store)
    prober = _agent("prober", trigger_type=EventType.USER_INPUT)
    skeptic = _agent("skeptic", trigger_type=EventType.USER_INPUT)
    current = _make_event(room.id, type=EventType.USER_INPUT, content="q")
    store.append(current)

    # prober ("prober" < "skeptic") should dispatch first → gets first mock response
    router = _mock_router("prober reply", "skeptic reply")
    result = dispatch_turn(
        {"skeptic": skeptic, "prober": prober},  # insertion order reversed
        room,
        current,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools={},
    )

    assert result.total_asked == 2
    assert result.failed_agents == []
    assert len(result.utterances) == 2
    assert result.utterances[0].author == build_author("prober")
    assert result.utterances[1].author == build_author("skeptic")
    assert result.utterances[0].content == "prober reply"
    assert result.utterances[1].content == "skeptic reply"


# ---------------------------------------------------------------------------
# 3. No agent speaks → TurnResult with total_asked=0
# ---------------------------------------------------------------------------


def test_dispatch_no_agent_speaks() -> None:
    store = _make_store()
    room = _make_room(store)
    # Agent triggers on HYPOTHESIS but we send USER_INPUT
    agent = _agent("alpha", trigger_type=EventType.HYPOTHESIS)
    current = _make_event(room.id, type=EventType.USER_INPUT)
    store.append(current)

    router = _mock_router()
    result = dispatch_turn(
        {"alpha": agent},
        room,
        current,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools={},
    )

    assert result.total_asked == 0
    assert result.utterances == []
    assert result.failed_agents == []
    router.call.assert_not_called()


# ---------------------------------------------------------------------------
# 4. All agents fail LLM exception → failed_agents filled, utterances empty
# ---------------------------------------------------------------------------


def test_dispatch_all_agents_fail_llm_exception() -> None:
    store = _make_store()
    room = _make_room(store)
    prober = _agent("prober", trigger_type=EventType.USER_INPUT)
    skeptic = _agent("skeptic", trigger_type=EventType.USER_INPUT)
    current = _make_event(room.id, type=EventType.USER_INPUT, content="q")
    store.append(current)

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = RuntimeError("provider down")

    result = dispatch_turn(
        {"prober": prober, "skeptic": skeptic},
        room,
        current,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools={},
    )

    assert result.total_asked == 2
    assert result.utterances == []
    assert sorted(result.failed_agents) == ["prober", "skeptic"]


# ---------------------------------------------------------------------------
# 5. §2 snapshot-semantics: snapshot frozen at turn start
# ---------------------------------------------------------------------------


def test_dispatch_snapshot_frozen_at_turn_start() -> None:
    """§2: prober speaks first; skeptic's should_agent_speak call uses the
    same snapshot taken at turn entry — it does NOT see prober's utterance."""
    store = _make_store()
    room = _make_room(store)
    prober = _agent("prober", trigger_type=EventType.USER_INPUT)
    skeptic = _agent("skeptic", trigger_type=EventType.USER_INPUT)
    current = _make_event(room.id, type=EventType.USER_INPUT, content="q")
    store.append(current)

    # Capture the snapshot seen by each should_agent_speak call
    snapshots_seen: list[list[Event]] = []
    real_sas = __import__(
        "orchestrator.agents.speaking", fromlist=["should_agent_speak"]
    ).should_agent_speak

    def _capturing_sas(
        agent: Agent,
        snapshot: list[Event],
        *,
        current_event: Event,
        regex_registry: Any,
    ) -> Any:
        snapshots_seen.append(list(snapshot))
        return real_sas(agent, snapshot, current_event=current_event, regex_registry=regex_registry)

    router = _mock_router("prober reply", "skeptic reply")

    with patch("orchestrator.agents.dispatch.should_agent_speak", side_effect=_capturing_sas):
        dispatch_turn(
            {"prober": prober, "skeptic": skeptic},
            room,
            current,
            event_store=store,
            llm_router=router,
            available_skills={},
            regex_registry={},
            tools={},
        )

    # Both agents received the same snapshot (taken before turn started)
    assert len(snapshots_seen) == 2
    # Neither snapshot contains an UTTERANCE authored by prober or skeptic
    for snap in snapshots_seen:
        utterance_authors = {e.author for e in snap if e.type == EventType.UTTERANCE}
        assert build_author("prober") not in utterance_authors
        assert build_author("skeptic") not in utterance_authors


def test_dispatch_subsequent_turn_sees_prior_utterance() -> None:
    """§2 cross-turn: after dispatch_turn completes, a second call sees the
    first turn's utterances in its snapshot."""
    store = _make_store()
    room = _make_room(store)
    agent = _agent("alpha", trigger_type=EventType.USER_INPUT)
    current1 = _make_event(room.id, type=EventType.USER_INPUT, content="first")
    store.append(current1)

    router = _mock_router("alpha first reply", "alpha second reply")
    dispatch_turn(
        {"alpha": agent},
        room,
        current1,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools={},
    )

    # Second turn: the event_store now includes the utterance from turn 1
    current2 = _make_event(room.id, type=EventType.USER_INPUT, content="second")
    store.append(current2)
    result2 = dispatch_turn(
        {"alpha": agent},
        room,
        current2,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools={},
    )

    snapshot2 = store.get_room_events(room.id)
    utterance_authors = {e.author for e in snapshot2 if e.type == EventType.UTTERANCE}
    assert build_author("alpha") in utterance_authors
    assert result2.total_asked == 1


# ---------------------------------------------------------------------------
# 6. §3 LLM exception: log + skip + continue (ADR-011 D7)
# ---------------------------------------------------------------------------


def test_dispatch_llm_exception_logs_and_continues(caplog: Any) -> None:
    """§3: prober raises RuntimeError; skeptic still dispatches; caplog has WARNING."""
    import logging

    store = _make_store()
    room = _make_room(store)
    prober = _agent("prober", trigger_type=EventType.USER_INPUT)
    skeptic = _agent("skeptic", trigger_type=EventType.USER_INPUT)
    current = _make_event(room.id, type=EventType.USER_INPUT, content="q")
    store.append(current)

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = [
        RuntimeError("simulated provider failure"),
        _llm_response("skeptic ok"),
    ]

    with caplog.at_level(logging.WARNING, logger="orchestrator.agents.dispatch"):
        result = dispatch_turn(
            {"prober": prober, "skeptic": skeptic},
            room,
            current,
            event_store=store,
            llm_router=router,
            available_skills={},
            regex_registry={},
            tools={},
        )

    assert result.total_asked == 2
    assert result.failed_agents == ["prober"]
    assert len(result.utterances) == 1
    assert result.utterances[0].author == build_author("skeptic")

    # WARNING logged for prober
    warning_messages = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("prober" in m for m in warning_messages)


# ---------------------------------------------------------------------------
# 7. §3 event_store.append failure aborts turn (ADR-011 D7-b)
# ---------------------------------------------------------------------------


def test_dispatch_event_store_abort_on_append_failure() -> None:
    """§3: event_store.append raises; turn aborts; no further LLM calls made."""
    store = _make_store()
    room = _make_room(store)
    prober = _agent("prober", trigger_type=EventType.USER_INPUT)
    skeptic = _agent("skeptic", trigger_type=EventType.USER_INPUT)
    current = _make_event(room.id, type=EventType.USER_INPUT, content="q")
    store.append(current)

    router = _mock_router("prober reply", "skeptic reply")

    with (
        patch.object(store, "append", side_effect=sqlite3.OperationalError("disk full")),
        pytest.raises(sqlite3.OperationalError, match="disk full"),
    ):
        dispatch_turn(
            {"prober": prober, "skeptic": skeptic},
            room,
            current,
            event_store=store,
            llm_router=router,
            available_skills={},
            regex_registry={},
            tools={},
        )

    # Only one LLM call was made (prober's); skeptic's was never reached
    assert router.call.call_count == 1


# ---------------------------------------------------------------------------
# 8. BaseException propagates unwrapped
# ---------------------------------------------------------------------------


def test_dispatch_base_exception_propagates() -> None:
    """KeyboardInterrupt is not caught — turn aborts cleanly."""
    store = _make_store()
    room = _make_room(store)
    agent = _agent("alpha", trigger_type=EventType.USER_INPUT)
    current = _make_event(room.id, type=EventType.USER_INPUT, content="q")
    store.append(current)

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        dispatch_turn(
            {"alpha": agent},
            room,
            current,
            event_store=store,
            llm_router=router,
            available_skills={},
            regex_registry={},
            tools={},
        )


# ---------------------------------------------------------------------------
# 9. §1 source ≠ sink: utterance.author == build_author(agent_id)
# ---------------------------------------------------------------------------


def test_dispatch_utterance_author_equals_build_author() -> None:
    """§1: author string on the appended event derives from build_author helper."""
    store = _make_store()
    room = _make_room(store)
    agent = _agent("my-agent", trigger_type=EventType.USER_INPUT)
    current = _make_event(room.id, type=EventType.USER_INPUT, content="hi")
    store.append(current)

    router = _mock_router("reply")
    result = dispatch_turn(
        {"my-agent": agent},
        room,
        current,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools={},
    )

    assert result.utterances[0].author == build_author("my-agent")
    assert result.utterances[0].author == "agent:my-agent"
    # Sentinel check: NOT a plain agent id or some other format
    assert result.utterances[0].author != "my-agent"
    assert result.utterances[0].author != "agent:sentinel-not-in-loader"


# ---------------------------------------------------------------------------
# 10. TurnResult observable cases (§6 behavior tests)
# ---------------------------------------------------------------------------


def test_dispatch_turn_result_nothing_to_say() -> None:
    """Observable case 1: nothing-to-say → total_asked=0, empty lists."""
    store = _make_store()
    room = _make_room(store)
    agent = _agent("alpha", trigger_type=EventType.HYPOTHESIS)
    current = _make_event(room.id, type=EventType.USER_INPUT)
    store.append(current)

    result = dispatch_turn(
        {"alpha": agent},
        room,
        current,
        event_store=store,
        llm_router=_mock_router(),
        available_skills={},
        regex_registry={},
        tools={},
    )
    assert result.total_asked == 0
    assert result.utterances == []
    assert result.failed_agents == []


def test_dispatch_turn_result_n_success() -> None:
    """Observable case 2: N agents speak and succeed → total_asked=N, N utterances."""
    store = _make_store()
    room = _make_room(store)
    agents = {
        "a": _agent("a", trigger_type=EventType.USER_INPUT),
        "b": _agent("b", trigger_type=EventType.USER_INPUT),
    }
    current = _make_event(room.id, type=EventType.USER_INPUT, content="q")
    store.append(current)

    result = dispatch_turn(
        agents,
        room,
        current,
        event_store=store,
        llm_router=_mock_router("a reply", "b reply"),
        available_skills={},
        regex_registry={},
        tools={},
    )
    assert result.total_asked == 2
    assert len(result.utterances) == 2
    assert result.failed_agents == []


def test_dispatch_turn_result_n_all_fail() -> None:
    """Observable case 3: N speak but all fail → total_asked=N, utterances=[], N failed."""
    store = _make_store()
    room = _make_room(store)
    agents = {
        "a": _agent("a", trigger_type=EventType.USER_INPUT),
        "b": _agent("b", trigger_type=EventType.USER_INPUT),
    }
    current = _make_event(room.id, type=EventType.USER_INPUT, content="q")
    store.append(current)

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = RuntimeError("all down")

    result = dispatch_turn(
        agents,
        room,
        current,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools={},
    )
    assert result.total_asked == 2
    assert result.utterances == []
    assert len(result.failed_agents) == 2


# ---------------------------------------------------------------------------
# 11. LLMRequest carries correct purpose and caller_agent_id
# ---------------------------------------------------------------------------


def test_dispatch_llm_request_purpose_and_caller() -> None:
    """Verify the LLMRequest sent to the router has correct purpose + caller_agent_id."""
    store = _make_store()
    room = _make_room(store)
    agent = _agent("alpha", trigger_type=EventType.USER_INPUT)
    current = _make_event(room.id, type=EventType.USER_INPUT, content="test")
    store.append(current)

    captured_requests: list[LLMRequest] = []

    def _capture_call(request: LLMRequest) -> LLMResponse:
        captured_requests.append(request)
        return _llm_response("ok")

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = _capture_call

    dispatch_turn(
        {"alpha": agent},
        room,
        current,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools={},
    )

    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.purpose == LLMPurpose.AGENT_RESPONSE
    assert req.caller_agent_id == "alpha"
    assert len(req.messages) >= 1


# ---------------------------------------------------------------------------
# 12. §1 tool-call dispatch integration: LLM returns tool_calls → events in store
# ---------------------------------------------------------------------------


def test_dispatch_tool_calls_auto_execute_creates_events() -> None:
    """§1 integration: operator LLM response with tool_call → tool_call event in store.

    Source ≠ sink: tool_id flows operator LLM response.tool_calls[0].name →
    process_tool_calls → ToolCallMeta.tool_name in stored event.
    """
    from orchestrator.autonomy.scoring import ToolMeta
    from orchestrator.llm.types import ToolCall

    store = _make_store()
    room = _make_room(store)
    # Agent with autonomy_thresholds that auto-executes a reversibility=10 tool
    # threshold_auto=8, confirm=4; read_file has reversibility=10 → AUTO_EXECUTE
    agent = _agent("operator", trigger_type=EventType.USER_INPUT)
    current = _make_event(room.id, type=EventType.USER_INPUT, content="fetch something")
    store.append(current)

    # LLM response includes a tool call
    def _router_with_tool_calls(request: object) -> LLMResponse:
        return LLMResponse(
            request_id=generate_request_id(),
            content="I'll read that file",
            model_id_requested=ModelId("m1"),
            model_id_used=ModelId("m1"),
            provider_id_used=_PROVIDER,
            usage=Usage(input_tokens=10, output_tokens=20),
            latency_ms=100,
            finish_reason="tool_use",
            tool_calls=[ToolCall(id="tc_001", name="read_file", arguments={"path": "foo.txt"})],
        )

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = _router_with_tool_calls

    tools = {"read_file": ToolMeta(reversibility=10)}
    result = dispatch_turn(
        {"operator": agent},
        room,
        current,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools=tools,
    )

    assert result.total_asked == 1
    assert len(result.utterances) == 1

    events = store.get_room_events(room.id)
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].metadata["tool_name"] == "read_file"
    assert tool_call_events[0].metadata["call_id"] == "tc_001"

    autonomy_events = [e for e in events if e.type == EventType.AUTONOMY_DECISION]
    assert len(autonomy_events) == 1


# ---------------------------------------------------------------------------
# 13. Logger + state_transition(snapshot_pending) → summary_snapshot in store
# ---------------------------------------------------------------------------


def test_dispatch_logger_produces_summary_snapshot_on_snapshot_pending() -> None:
    """§1 integration: Logger agent triggered by state_transition(snapshot_pending)
    → dispatch_turn appends summary_snapshot event to event_store.

    Source ≠ sink: state_transition.metadata.new_state → produce_and_emit_snapshot
    → SUMMARY_SNAPSHOT event in event_store with SummarySnapshotMeta metadata.
    """
    from orchestrator.agents.schema import StateChangeTrigger

    store = _make_store()
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH, state="snapshot_pending")
    store.append_room(room)

    logger_agent = Agent(
        id="logger",
        role="logger",
        persona="I am the Logger.",
        llm_config=_LLM,
        speaking_triggers=[StateChangeTrigger(target_state="snapshot_pending")],
    )

    st_event = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.STATE_TRANSITION,
        author="system",
        timestamp=now_ms(),
        content="",
        metadata={"new_state": "snapshot_pending", "prior_state": "convergence"},
    )
    store.append(st_event)

    router = _mock_router("Logger acknowledged snapshot_pending.")
    result = dispatch_turn(
        {"logger": logger_agent},
        room,
        st_event,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry={},
        tools={},
    )

    assert result.total_asked == 1
    assert result.failed_agents == []

    events = store.get_room_events(room.id)
    ss_events = [e for e in events if e.type == EventType.SUMMARY_SNAPSHOT]
    assert len(ss_events) == 1, f"Expected 1 SUMMARY_SNAPSHOT event, got {len(ss_events)}"
    assert ss_events[0].author == build_author("logger")
