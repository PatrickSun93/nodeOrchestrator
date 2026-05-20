"""Behavior tests for ``orchestrator.autonomy.emission``."""

from __future__ import annotations

import pytest

from orchestrator.autonomy.emission import emit_gate_decision
from orchestrator.autonomy.scoring import (
    AutonomyScore,
    AutonomyTier,
    Operation,
    ThresholdConfig,
    ToolMeta,
    UnknownToolError,
)
from orchestrator.core.event import EventType, RoomId
from orchestrator.core.event_store import EventStore

_OPERATOR = ThresholdConfig(threshold_auto=6, threshold_confirm=3, user_intent_modifier=3)


def _op(tool_id: str, *, user_explicit_intent: bool = False) -> Operation:
    return Operation(
        tool_id=tool_id,
        initiating_agent="agent:operator",
        user_explicit_intent=user_explicit_intent,
    )


def _tools(*pairs: tuple[str, int]) -> dict[str, ToolMeta]:
    return {tid: ToolMeta(reversibility=rev) for tid, rev in pairs}


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_emit_success_returns_autonomy_score(event_store: EventStore, room_id: RoomId) -> None:
    tools = _tools(("read_file", 10))
    result = emit_gate_decision(
        _op("read_file"), tools, _OPERATOR, event_store, room_id=room_id, author="agent:operator"
    )
    assert isinstance(result, AutonomyScore)
    assert result.tier == AutonomyTier.AUTO_EXECUTE


def test_emit_success_writes_autonomy_decision_event(
    event_store: EventStore, room_id: RoomId
) -> None:
    tools = _tools(("read_file", 10))
    result = emit_gate_decision(
        _op("read_file"), tools, _OPERATOR, event_store, room_id=room_id, author="agent:operator"
    )
    events = event_store.get_room_events(room_id)
    decision_events = [e for e in events if e.type == EventType.AUTONOMY_DECISION]
    assert len(decision_events) == 1
    meta = decision_events[0].metadata
    assert meta["operation_tool_id"] == "read_file"
    assert meta["score"] == result.score
    assert meta["tier"] == result.tier.value
    assert meta["rule"] == result.trace.rule


def test_emit_success_no_refusal_event(event_store: EventStore, room_id: RoomId) -> None:
    tools = _tools(("read_file", 10))
    emit_gate_decision(
        _op("read_file"), tools, _OPERATOR, event_store, room_id=room_id, author="agent:operator"
    )
    events = event_store.get_room_events(room_id)
    assert not any(e.type == EventType.AUTONOMY_REFUSAL for e in events)


# ---------------------------------------------------------------------------
# Refusal path
# ---------------------------------------------------------------------------


def test_emit_refusal_raises_unknown_tool_error(event_store: EventStore, room_id: RoomId) -> None:
    with pytest.raises(UnknownToolError) as exc_info:
        emit_gate_decision(
            _op("ghost_tool"), {}, _OPERATOR, event_store, room_id=room_id, author="agent:operator"
        )
    assert exc_info.value.tool_id == "ghost_tool"


def test_emit_refusal_writes_autonomy_refusal_event(
    event_store: EventStore, room_id: RoomId
) -> None:
    with pytest.raises(UnknownToolError):
        emit_gate_decision(
            _op("ghost_tool"), {}, _OPERATOR, event_store, room_id=room_id, author="agent:operator"
        )
    events = event_store.get_room_events(room_id)
    refusal_events = [e for e in events if e.type == EventType.AUTONOMY_REFUSAL]
    assert len(refusal_events) == 1
    meta = refusal_events[0].metadata
    assert meta["operation_tool_id"] == "ghost_tool"
    assert meta["refusal_reason"] == "unknown_tool"
    assert meta["user_explicit_intent"] is False


def test_emit_refusal_no_decision_event(event_store: EventStore, room_id: RoomId) -> None:
    with pytest.raises(UnknownToolError):
        emit_gate_decision(
            _op("ghost_tool"), {}, _OPERATOR, event_store, room_id=room_id, author="agent:operator"
        )
    events = event_store.get_room_events(room_id)
    assert not any(e.type == EventType.AUTONOMY_DECISION for e in events)


# ---------------------------------------------------------------------------
# Ordering: event appended before raise
# ---------------------------------------------------------------------------


def test_emit_refusal_event_appended_before_raise(room_id: RoomId) -> None:
    """Verify the refusal event is appended before UnknownToolError propagates.

    Uses a mock store that records the sequence of append calls, ensuring
    the append happened even if the outer caller's handler runs immediately.
    """

    class _Recorder:
        def __init__(self) -> None:
            self.appended: list[str] = []

        def append(self, event: object) -> object:
            from orchestrator.core.event import Event

            assert isinstance(event, Event)
            self.appended.append(event.type.value)
            return event.id

    recorder = _Recorder()

    with pytest.raises(UnknownToolError):
        emit_gate_decision(
            _op("ghost_tool"),
            {},
            _OPERATOR,
            recorder,  # type: ignore[arg-type]
            room_id=room_id,
            author="agent:operator",
        )

    assert recorder.appended == ["autonomy_refusal"], (
        f"Expected exactly one autonomy_refusal append before the raise; got: {recorder.appended}"
    )
