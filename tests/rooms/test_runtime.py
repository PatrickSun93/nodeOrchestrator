"""Tests for rooms/runtime.py — run_turn orchestrator.

Covers:
  §1  cross-module integration (Research room → state machine → dispatch)
  §3  cleanup: event_store abort propagates (ADR-011 D7-b via dispatch_turn)
  §4  exception payload: RoomStateError propagates from next_room_state
  §6  schema invariants: StateTransitionMeta metadata in appended event
"""

from __future__ import annotations

import sqlite3
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.agents.schema import (
    Agent,
    AgentAppliesTo,
    EventTypeTrigger,
    RegexTrigger,
    StateChangeTrigger,
)
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    StateTransitionMeta,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.types import (
    AgentAutonomyThresholds,
    AgentLLMConfig,
    LLMResponse,
    ModelId,
    ProviderId,
    Usage,
    generate_request_id,
)
from orchestrator.rooms.exceptions import RoomStateError
from orchestrator.rooms.runtime import run_turn

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTONOMY = AgentAutonomyThresholds(
    threshold_auto=8,
    threshold_confirm=4,
    user_intent_modifier=2,
)
_LLM = AgentLLMConfig(default_model=ModelId("m1"), autonomy_thresholds=_AUTONOMY)
_PROVIDER = ProviderId("p1")


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room(
    store: EventStore,
    *,
    room_type: RoomType = RoomType.RESEARCH,
    state: str = "setup",
) -> Room:
    room = Room(id=generate_room_id(), type=room_type, state=state)
    store.append_room(room)
    return room


def _make_event(
    room_id: RoomId,
    *,
    event_type: EventType = EventType.UTTERANCE,
    content: str = "hello",
) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=event_type,
        author="user",
        timestamp=now_ms(),
        content=content,
    )


def _llm_response(content: str = "agent response") -> LLMResponse:
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


def _mock_router(content: str = "agent response") -> MagicMock:
    router = MagicMock()
    router.call.return_value = _llm_response(content)
    return router


def _agent(
    agent_id: str,
    *,
    triggers: list[EventTypeTrigger] | None = None,
    room_types: list[str] | None = None,
    room_states: list[str] | None = None,
) -> Agent:
    return Agent(
        id=agent_id,
        role="r",
        persona=f"I am {agent_id}",
        llm_config=_LLM,
        speaking_triggers=cast(
            list[RegexTrigger | EventTypeTrigger | StateChangeTrigger], triggers or []
        ),
        applies_to=AgentAppliesTo(
            room_types=room_types or ["*"],
            room_states=room_states or ["*"],
        ),
    )


# ---------------------------------------------------------------------------
# 1. No transition → no state_transition event
# ---------------------------------------------------------------------------


def test_no_transition_no_state_event() -> None:
    """No state_transition event appended when next_room_state returns None."""
    store = _make_store()
    # utterance in "exploration" state doesn't trigger any Research transition
    room = _make_room(store, state="exploration")
    evt = _make_event(room.id, event_type=EventType.UTTERANCE)

    run_turn(
        room,
        evt,
        available_agents={},
        available_skills={},
        event_store=store,
        llm_router=_mock_router(),
        regex_registry={},
        tools={},
    )

    types = [e.type for e in store.get_room_events(room.id)]
    assert EventType.STATE_TRANSITION not in types


# ---------------------------------------------------------------------------
# 2. State transition fires → event appended to store
# ---------------------------------------------------------------------------


def test_transition_fires_appends_state_transition_event() -> None:
    """setup → exploration: state_transition event appended with correct metadata."""
    store = _make_store()
    room = _make_room(store, state="setup")
    evt = _make_event(room.id, event_type=EventType.UTTERANCE)

    run_turn(
        room,
        evt,
        available_agents={},
        available_skills={},
        event_store=store,
        llm_router=_mock_router(),
        regex_registry={},
        tools={},
    )

    events = store.get_room_events(room.id)
    transition_events = [e for e in events if e.type == EventType.STATE_TRANSITION]
    assert len(transition_events) == 1
    meta = StateTransitionMeta.model_validate(transition_events[0].metadata)
    assert meta.prior_state == "setup"
    assert meta.new_state == "exploration"
    assert transition_events[0].author == "system"


# ---------------------------------------------------------------------------
# 3. State transition event is appended BEFORE dispatch utterances
# ---------------------------------------------------------------------------


def test_state_transition_event_before_utterance() -> None:
    """State transition event appears before agent utterance in event log."""
    store = _make_store()
    room = _make_room(store, state="setup")
    agent = _agent("a", triggers=[EventTypeTrigger(event_type=EventType.UTTERANCE)])
    evt = _make_event(room.id, event_type=EventType.UTTERANCE)

    store.append(evt)
    run_turn(
        room,
        evt,
        available_agents={"a": agent},
        available_skills={},
        event_store=store,
        llm_router=_mock_router(),
        regex_registry={},
        tools={},
    )

    events = store.get_room_events(room.id)
    types = [e.type for e in events]
    assert EventType.STATE_TRANSITION in types
    assert EventType.UTTERANCE in types
    state_idx = types.index(EventType.STATE_TRANSITION)
    # Two UTTERANCEs: trigger (appended before run_turn) + agent response.
    # STATE_TRANSITION must precede the agent's utterance (last UTTERANCE).
    utterance_indices = [i for i, t in enumerate(types) if t == EventType.UTTERANCE]
    assert len(utterance_indices) >= 2
    assert state_idx < utterance_indices[-1]


# ---------------------------------------------------------------------------
# 4. room.state not mutated (Room is frozen)
# ---------------------------------------------------------------------------


def test_room_state_not_mutated() -> None:
    """run_turn does not mutate room.state; Room is a frozen Pydantic model."""
    store = _make_store()
    room = _make_room(store, state="setup")
    original_state = room.state
    evt = _make_event(room.id, event_type=EventType.UTTERANCE)

    run_turn(
        room,
        evt,
        available_agents={},
        available_skills={},
        event_store=store,
        llm_router=_mock_router(),
        regex_registry={},
        tools={},
    )

    assert room.state == original_state  # frozen — not mutated by run_turn
    # New state is persisted in the event log
    transition_events = [
        e for e in store.get_room_events(room.id) if e.type == EventType.STATE_TRANSITION
    ]
    assert len(transition_events) == 1
    meta = StateTransitionMeta.model_validate(transition_events[0].metadata)
    assert meta.new_state == "exploration"


# ---------------------------------------------------------------------------
# 5. Dispatch-time room_state filter
# ---------------------------------------------------------------------------


def test_dispatch_time_filter_excludes_wrong_room_state() -> None:
    """Agent with room_states=["exploration"] is excluded when room.state="setup"."""
    store = _make_store()
    room = _make_room(store, state="setup")
    # USER_INPUT in "setup" does not trigger setup→exploration (only UTTERANCE does)
    agent = _agent(
        "a",
        triggers=[EventTypeTrigger(event_type=EventType.USER_INPUT)],
        room_states=["exploration"],  # won't match "setup"
    )
    evt = _make_event(room.id, event_type=EventType.USER_INPUT)

    llm = _mock_router()
    run_turn(
        room,
        evt,
        available_agents={"a": agent},
        available_skills={},
        event_store=store,
        llm_router=llm,
        regex_registry={},
        tools={},
    )

    llm.call.assert_not_called()
    utterances = [e for e in store.get_room_events(room.id) if e.type == EventType.UTTERANCE]
    assert utterances == []


def test_wildcard_room_states_always_active() -> None:
    """Agent with applies_to.room_states=["*"] is active in any room state."""
    store = _make_store()
    room = _make_room(store, state="convergence")
    agent = _agent(
        "prober",
        triggers=[EventTypeTrigger(event_type=EventType.UTTERANCE)],
        room_states=["*"],  # matches any state
    )
    # UTTERANCE in convergence state: no typed metadata required, no state transition fires
    evt = _make_event(room.id, event_type=EventType.UTTERANCE)

    store.append(evt)
    result = run_turn(
        room,
        evt,
        available_agents={"prober": agent},
        available_skills={},
        event_store=store,
        llm_router=_mock_router(),
        regex_registry={},
        tools={},
    )

    assert result.total_asked == 1
    assert len(result.utterances) == 1


# ---------------------------------------------------------------------------
# 6. RoomStateError propagates
# ---------------------------------------------------------------------------


def test_room_state_error_propagates() -> None:
    """§4 exception payload: RoomStateError from next_room_state propagates unwrapped."""
    store = _make_store()
    room = _make_room(store, state="setup")
    evt = _make_event(room.id, event_type=EventType.UTTERANCE)

    err = RoomStateError(room.id, "setup", "test_rule")
    with (
        patch("orchestrator.rooms.runtime.next_room_state", side_effect=err),
        pytest.raises(RoomStateError) as exc_info,
    ):
        run_turn(
            room,
            evt,
            available_agents={},
            available_skills={},
            event_store=store,
            llm_router=_mock_router(),
            regex_registry={},
            tools={},
        )
    assert exc_info.value.room_id == room.id
    assert exc_info.value.attempted_transition_rule == "test_rule"


# ---------------------------------------------------------------------------
# 7. Empty agents → nothing-to-say TurnResult
# ---------------------------------------------------------------------------


def test_empty_agents_returns_nothing_to_say() -> None:
    """Empty available_agents → TurnResult(total_asked=0, utterances=[])."""
    store = _make_store()
    room = _make_room(store, state="exploration")
    evt = _make_event(room.id, event_type=EventType.USER_INPUT)

    result = run_turn(
        room,
        evt,
        available_agents={},
        available_skills={},
        event_store=store,
        llm_router=_mock_router(),
        regex_registry={},
        tools={},
    )

    assert result.total_asked == 0
    assert result.utterances == []
    assert result.failed_agents == []


# ---------------------------------------------------------------------------
# 8. §1 cross-module integration test
# ---------------------------------------------------------------------------


def test_integration_research_room_state_advance_and_agent_speaks() -> None:
    """§1 integration: Research room setup→exploration + agent utterance.

    Source ≠ sink: skeptic.id flows through the full pipeline (load →
    dispatch → utterance author); the utterance author is agent:skeptic,
    not any default sentinel.
    """
    store = _make_store()
    room = _make_room(store, state="setup")

    skeptic = _agent(
        "skeptic",
        triggers=[EventTypeTrigger(event_type=EventType.UTTERANCE)],
    )
    prober = _agent(
        "prober",
        triggers=[EventTypeTrigger(event_type=EventType.UTTERANCE)],
    )
    agents = {"skeptic": skeptic, "prober": prober}
    evt = _make_event(room.id, event_type=EventType.UTTERANCE)

    store.append(evt)
    result = run_turn(
        room,
        evt,
        available_agents=agents,
        available_skills={},
        event_store=store,
        llm_router=_mock_router("a response"),
        regex_registry={},
        tools={},
    )

    # State advanced setup → exploration
    events = store.get_room_events(room.id)
    transition_events = [e for e in events if e.type == EventType.STATE_TRANSITION]
    assert len(transition_events) == 1
    meta = StateTransitionMeta.model_validate(transition_events[0].metadata)
    assert meta.prior_state == "setup"
    assert meta.new_state == "exploration"

    # Both agents spoke — sources are the actual agent ids (not a sentinel)
    utterance_authors = {e.author for e in events if e.type == EventType.UTTERANCE}
    assert "agent:skeptic" in utterance_authors
    assert "agent:prober" in utterance_authors
    assert result.total_asked == 2
    assert len(result.utterances) == 2


def test_run_turn_tools_param_threads_through() -> None:
    """tools parameter passed to run_turn is threaded to dispatch_turn/process_tool_calls."""
    from orchestrator.autonomy.scoring import ToolMeta
    from orchestrator.llm.types import (
        LLMResponse,
        ModelId,
        ProviderId,
        ToolCall,
        Usage,
        generate_request_id,
    )

    store = _make_store()
    room = _make_room(store, state="exploration")
    agent = _agent("op", triggers=[EventTypeTrigger(event_type=EventType.USER_INPUT)])
    evt = _make_event(room.id, event_type=EventType.USER_INPUT)
    store.append(evt)

    def _router_with_tool_calls(request: object) -> LLMResponse:
        return LLMResponse(
            request_id=generate_request_id(),
            content="calling tool",
            model_id_requested=ModelId("m1"),
            model_id_used=ModelId("m1"),
            provider_id_used=ProviderId("p1"),
            usage=Usage(input_tokens=5, output_tokens=5),
            latency_ms=10,
            finish_reason="tool_use",
            tool_calls=[ToolCall(id="tc_r", name="read_file", arguments={})],
        )

    router = MagicMock()
    router.call.side_effect = _router_with_tool_calls

    tools = {"read_file": ToolMeta(reversibility=10)}
    result = run_turn(
        room,
        evt,
        available_agents={"op": agent},
        available_skills={},
        event_store=store,
        llm_router=router,
        regex_registry={},
        tools=tools,
    )

    assert result.total_asked == 1
    events = store.get_room_events(room.id)
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].metadata["tool_name"] == "read_file"


# ---------------------------------------------------------------------------
# P4.1-1: select_dispatch_agents — unit tests
# ---------------------------------------------------------------------------


def test_select_dispatch_agents_load_time_room_type_filter() -> None:
    """Load-time filter: agent with non-matching room_types excluded."""
    from orchestrator.rooms.runtime import select_dispatch_agents

    store = _make_store()
    room = _make_room(store, room_type=RoomType.RESEARCH, state="exploration")
    agent_match = _agent("a1", room_types=["research"], room_states=["*"])
    agent_no_match = _agent("a2", room_types=["bug_fix"], room_states=["*"])

    result = select_dispatch_agents(room, {"a1": agent_match, "a2": agent_no_match})
    assert "a1" in result
    assert "a2" not in result


def test_select_dispatch_agents_dispatch_time_room_state_filter() -> None:
    """Dispatch-time filter: agent with non-matching room_states excluded."""
    from orchestrator.rooms.runtime import select_dispatch_agents

    store = _make_store()
    room = _make_room(store, state="setup")
    agent_match = _agent("b1", room_states=["setup"])
    agent_no_match = _agent("b2", room_states=["exploration"])

    result = select_dispatch_agents(room, {"b1": agent_match, "b2": agent_no_match})
    assert "b1" in result
    assert "b2" not in result


def test_select_dispatch_agents_wildcard_room_states() -> None:
    """Wildcard room_states matches any room state."""
    from orchestrator.rooms.runtime import select_dispatch_agents

    store = _make_store()
    room = _make_room(store, state="convergence")
    agent_wild = _agent("c1", room_states=["*"])

    result = select_dispatch_agents(room, {"c1": agent_wild})
    assert "c1" in result


def test_select_dispatch_agents_pure_no_side_effects() -> None:
    """select_dispatch_agents is pure: no events appended to store."""
    from orchestrator.rooms.runtime import select_dispatch_agents

    store = _make_store()
    room = _make_room(store, state="setup")
    agent = _agent("d1", room_types=["*"], room_states=["*"])
    before = len(store.get_room_events(room.id))

    select_dispatch_agents(room, {"d1": agent})

    assert len(store.get_room_events(room.id)) == before
