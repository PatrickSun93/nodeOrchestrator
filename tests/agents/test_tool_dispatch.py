"""Tests for src/orchestrator/agents/tool_dispatch.py.

§1 cross-module integration: process_tool_calls consumes pre-parsed ToolCall
instances and emits events into EventStore.
§3 cleanup: UnknownToolError + event_store.append exception handling.
§6 schema invariants: ToolDispatchResult / ToolDispatchDecision frozen models.
"""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from orchestrator.agents.tool_dispatch import (
    ToolDispatchDecision,
    ToolDispatchResult,
    process_tool_calls,
)
from orchestrator.autonomy.scoring import AutonomyTier, ThresholdConfig, ToolMeta
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    ToolCallPendingMeta,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.types import ToolCall

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_THRESHOLDS = ThresholdConfig(threshold_auto=6, threshold_confirm=3, user_intent_modifier=3)

_TOOLS: dict[str, ToolMeta] = {
    "read_file": ToolMeta(reversibility=10),  # AUTO_EXECUTE vs _THRESHOLDS (10 >= 6)
    "apply_edit": ToolMeta(reversibility=2),  # HARD_CONFIRM vs _THRESHOLDS (2 < 3)
    "propose_edit": ToolMeta(reversibility=5),  # COUNTDOWN_CONFIRM vs _THRESHOLDS (3 <= 5 < 6)
}


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:")
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room(store: EventStore) -> RoomId:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


def _make_event(room_id: RoomId, *, type: EventType = EventType.UTTERANCE) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=type,
        author="agent:operator",
        timestamp=now_ms(),
        content="run the tool",
    )


def _tool_call(
    name: str, call_id: str = "call_1", arguments: dict[str, object] | None = None
) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=arguments or {})


# ---------------------------------------------------------------------------
# §1 cross-module: AUTO_EXECUTE path
# ---------------------------------------------------------------------------


def test_auto_execute_appends_autonomy_decision_and_tool_call_events() -> None:
    """AUTO_EXECUTE: autonomy_decision lands before tool_call in stream."""
    store = _make_store()
    room_id = _make_room(store)
    current = _make_event(room_id, type=EventType.USER_INPUT)
    store.append(current)

    result = process_tool_calls(
        [_tool_call("read_file")],
        agent_id="operator",
        room_id=room_id,
        current_event=current,
        event_store=store,
        tools=_TOOLS,
        thresholds=_THRESHOLDS,
    )

    assert len(result.decisions) == 1
    d = result.decisions[0]
    assert d.tier == AutonomyTier.AUTO_EXECUTE
    assert d.tool_call_event_appended is True
    assert d.refusal_reason is None

    events = store.get_room_events(room_id)
    # Filter post-trigger events
    types = [e.type for e in events if e.id != current.id]
    assert EventType.AUTONOMY_DECISION in types
    assert EventType.TOOL_CALL in types
    # Causal ordering: decision before action (ADR-013 D2)
    decision_idx = next(i for i, e in enumerate(events) if e.type == EventType.AUTONOMY_DECISION)
    tool_call_idx = next(i for i, e in enumerate(events) if e.type == EventType.TOOL_CALL)
    assert decision_idx < tool_call_idx


# ---------------------------------------------------------------------------
# §1 cross-module: COUNTDOWN_CONFIRM path
# ---------------------------------------------------------------------------


def test_countdown_confirm_appends_autonomy_decision_and_tool_call_pending() -> None:
    """COUNTDOWN_CONFIRM: autonomy_decision + tool_call_pending emitted, no tool_call."""
    store = _make_store()
    room_id = _make_room(store)
    current = _make_event(room_id, type=EventType.UTTERANCE)  # non-user: no threshold reduction
    store.append(current)

    result = process_tool_calls(
        [_tool_call("propose_edit", call_id="call_cd")],
        agent_id="operator",
        room_id=room_id,
        current_event=current,
        event_store=store,
        tools=_TOOLS,
        thresholds=_THRESHOLDS,
    )

    assert len(result.decisions) == 1
    d = result.decisions[0]
    assert d.tier == AutonomyTier.COUNTDOWN_CONFIRM
    assert d.tool_call_event_appended is False

    events = store.get_room_events(room_id)
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 0
    decision_events = [e for e in events if e.type == EventType.AUTONOMY_DECISION]
    assert len(decision_events) == 1

    # B1: TOOL_CALL_PENDING event appended with full payload (ADR-030 D1)
    pending_events = [e for e in events if e.type == EventType.TOOL_CALL_PENDING]
    assert len(pending_events) == 1
    p = pending_events[0]
    meta = ToolCallPendingMeta.model_validate(p.metadata)
    assert meta.tool_name == "propose_edit"
    assert meta.call_id == "call_cd"
    assert meta.tier == "countdown_confirm"
    assert meta.initiating_agent == "operator"
    assert p.author == "agent:operator"


# ---------------------------------------------------------------------------
# §1 cross-module: HARD_CONFIRM path
# ---------------------------------------------------------------------------


def test_hard_confirm_appends_autonomy_decision_and_tool_call_pending() -> None:
    """HARD_CONFIRM: autonomy_decision + tool_call_pending emitted, no tool_call."""
    store = _make_store()
    room_id = _make_room(store)
    current = _make_event(room_id, type=EventType.UTTERANCE)  # non-user: no threshold reduction
    store.append(current)

    result = process_tool_calls(
        [_tool_call("apply_edit", call_id="call_hc")],
        agent_id="operator",
        room_id=room_id,
        current_event=current,
        event_store=store,
        tools=_TOOLS,
        thresholds=_THRESHOLDS,
    )

    assert len(result.decisions) == 1
    d = result.decisions[0]
    assert d.tier == AutonomyTier.HARD_CONFIRM
    assert d.tool_call_event_appended is False

    events = store.get_room_events(room_id)
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 0

    # B1: TOOL_CALL_PENDING event appended with full payload (ADR-030 D1)
    pending_events = [e for e in events if e.type == EventType.TOOL_CALL_PENDING]
    assert len(pending_events) == 1
    meta = ToolCallPendingMeta.model_validate(pending_events[0].metadata)
    assert meta.tool_name == "apply_edit"
    assert meta.call_id == "call_hc"
    assert meta.tier == "hard_confirm"
    assert meta.initiating_agent == "operator"


# ---------------------------------------------------------------------------
# §3 cleanup: UnknownToolError path
# ---------------------------------------------------------------------------


def test_unknown_tool_records_refusal_and_continues() -> None:
    """UnknownToolError: autonomy_refusal event appended; decision recorded; batch continues."""
    store = _make_store()
    room_id = _make_room(store)
    current = _make_event(room_id, type=EventType.USER_INPUT)
    store.append(current)

    result = process_tool_calls(
        [_tool_call("ghost_tool", call_id="call_ghost")],
        agent_id="operator",
        room_id=room_id,
        current_event=current,
        event_store=store,
        tools=_TOOLS,
        thresholds=_THRESHOLDS,
    )

    assert len(result.decisions) == 1
    d = result.decisions[0]
    assert d.tier is None
    assert d.tool_call_event_appended is False
    assert d.refusal_reason == "unknown_tool"

    events = store.get_room_events(room_id)
    refusal_events = [e for e in events if e.type == EventType.AUTONOMY_REFUSAL]
    assert len(refusal_events) == 1
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 0


# ---------------------------------------------------------------------------
# §1 cross-module: mixed batch
# ---------------------------------------------------------------------------


def test_mixed_batch_three_calls() -> None:
    """3 tool calls (1 AUTO + 1 HARD + 1 unknown) -> 3 decisions; correct event counts."""
    store = _make_store()
    room_id = _make_room(store)
    current = _make_event(room_id, type=EventType.UTTERANCE)  # non-user: no threshold reduction
    store.append(current)

    result = process_tool_calls(
        [
            _tool_call("read_file", call_id="c1"),  # AUTO_EXECUTE
            _tool_call("apply_edit", call_id="c2"),  # HARD_CONFIRM
            _tool_call("ghost_tool", call_id="c3"),  # UnknownToolError
        ],
        agent_id="operator",
        room_id=room_id,
        current_event=current,
        event_store=store,
        tools=_TOOLS,
        thresholds=_THRESHOLDS,
    )

    assert len(result.decisions) == 3
    tiers = {d.call_id: d.tier for d in result.decisions}
    assert tiers["c1"] == AutonomyTier.AUTO_EXECUTE
    assert tiers["c2"] == AutonomyTier.HARD_CONFIRM
    assert tiers["c3"] is None

    events = store.get_room_events(room_id)
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 1  # only AUTO_EXECUTE
    refusal_events = [e for e in events if e.type == EventType.AUTONOMY_REFUSAL]
    assert len(refusal_events) == 1  # only ghost_tool
    decision_events = [e for e in events if e.type == EventType.AUTONOMY_DECISION]
    assert len(decision_events) == 2  # read_file + apply_edit


# ---------------------------------------------------------------------------
# §1 cross-module: user_explicit_intent derivation (ADR-013 D3)
# ---------------------------------------------------------------------------


def test_user_explicit_intent_lowers_effective_threshold() -> None:
    """USER_INPUT trigger lowers effective thresholds (ADR-013 D3 / ADR-005 D5).

    Tool with reversibility=5 (propose_edit):
    - Raw: auto=6, confirm=3. Score 5 < 6 → COUNTDOWN_CONFIRM.
    - With user_explicit_intent=True and modifier=3: eff_auto=3, eff_confirm=0.
      Score 5 >= 3 → AUTO_EXECUTE.
    """
    store = _make_store()
    room_id = _make_room(store)

    # Non-user trigger: expect COUNTDOWN_CONFIRM for propose_edit
    non_user_event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.UTTERANCE,  # system-internal, not USER_INPUT
        author="agent:skeptic",
        timestamp=now_ms(),
        content="",
    )
    store.append(non_user_event)

    result_non_user = process_tool_calls(
        [_tool_call("propose_edit", call_id="c_nu")],
        agent_id="operator",
        room_id=room_id,
        current_event=non_user_event,
        event_store=store,
        tools=_TOOLS,
        thresholds=_THRESHOLDS,
    )
    assert result_non_user.decisions[0].tier == AutonomyTier.COUNTDOWN_CONFIRM

    # User trigger: expect AUTO_EXECUTE for propose_edit
    user_event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.USER_INPUT,
        author="user",
        timestamp=now_ms(),
        content="do it",
    )
    store.append(user_event)

    result_user = process_tool_calls(
        [_tool_call("propose_edit", call_id="c_u")],
        agent_id="operator",
        room_id=room_id,
        current_event=user_event,
        event_store=store,
        tools=_TOOLS,
        thresholds=_THRESHOLDS,
    )
    assert result_user.decisions[0].tier == AutonomyTier.AUTO_EXECUTE


# ---------------------------------------------------------------------------
# §3 cleanup: event_store.append exception propagates unwrapped
# ---------------------------------------------------------------------------


def test_event_store_append_exception_propagates_unwrapped() -> None:
    """event_store.append raises → exception propagates unwrapped (ADR-011 D7-b)."""
    from unittest.mock import MagicMock

    store = _make_store()
    room_id = _make_room(store)
    current = _make_event(room_id, type=EventType.USER_INPUT)
    store.append(current)

    class _StoreError(Exception):
        pass

    boom_store = MagicMock(spec=EventStore)
    # First call (autonomy_decision append from emit_gate_decision) succeeds
    # Second call (tool_call append) raises
    boom_store.append.side_effect = [None, _StoreError("disk full")]

    with pytest.raises(_StoreError):
        process_tool_calls(
            [_tool_call("read_file")],
            agent_id="operator",
            room_id=room_id,
            current_event=current,
            event_store=boom_store,
            tools=_TOOLS,
            thresholds=_THRESHOLDS,
        )


# ---------------------------------------------------------------------------
# §6 schema invariants: ToolDispatchResult / ToolDispatchDecision
# ---------------------------------------------------------------------------


def test_tool_dispatch_decision_is_frozen() -> None:
    d = ToolDispatchDecision(
        call_id="c1",
        tool_name="read_file",
        tier=AutonomyTier.AUTO_EXECUTE,
        tool_call_event_appended=True,
        refusal_reason=None,
    )
    with pytest.raises((ValidationError, TypeError)):
        d.call_id = "mutated"


def test_tool_dispatch_result_is_frozen() -> None:
    r = ToolDispatchResult(decisions=[])
    with pytest.raises((ValidationError, TypeError)):
        r.decisions = []


def test_tool_dispatch_decision_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ToolDispatchDecision(
            call_id="c1",
            tool_name="t",
            tier=None,
            tool_call_event_appended=False,
            refusal_reason=None,
            extra_field="bad",  # type: ignore[call-arg]
        )


def test_tool_dispatch_result_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ToolDispatchResult(decisions=[], extra_field="bad")  # type: ignore[call-arg]
