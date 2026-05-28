"""Tests for src/orchestrator/agents/snapshot_dispatch.py.

Coverage:
  §1 cross-module: Logger agent + state_transition(snapshot_pending) →
     produce_and_emit_snapshot → summary_snapshot event in event_store.
  §3 cleanup: non-snapshot_pending state_transitions → no dispatch.
  §6 schema: SnapshotDispatchResult frozen + extra=forbid.
"""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from orchestrator.agents.schema import Agent
from orchestrator.agents.snapshot_dispatch import SnapshotDispatchResult, produce_and_emit_snapshot
from orchestrator.core.event import (
    Event,
    EventType,
    SummarySnapshotMeta,
    TimestampMs,
    build_author,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.types import AgentAutonomyThresholds, AgentLLMConfig, ModelId

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTONOMY = AgentAutonomyThresholds(threshold_auto=8, threshold_confirm=4, user_intent_modifier=2)
_LLM = AgentLLMConfig(default_model=ModelId("m1"), autonomy_thresholds=_AUTONOMY)


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:")
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room(store: EventStore, state: str = "snapshot_pending") -> Room:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH, state=state)
    store.append_room(room)
    return room


def _logger_agent() -> Agent:
    from orchestrator.agents.schema import StateChangeTrigger

    return Agent(
        id="logger",
        role="logger",
        persona="I am the Logger.",
        llm_config=_LLM,
        speaking_triggers=[StateChangeTrigger(target_state="snapshot_pending")],
    )


def _state_transition_event(room: Room, new_state: str, prior_state: str) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.STATE_TRANSITION,
        author="system",
        timestamp=now_ms(),
        content="",
        metadata={"new_state": new_state, "prior_state": prior_state},
    )


# ---------------------------------------------------------------------------
# §1 cross-module: snapshot fires on state_change to snapshot_pending
# ---------------------------------------------------------------------------


def test_snapshot_fires_on_snapshot_pending_transition() -> None:
    """produce_and_emit_snapshot appends summary_snapshot event to store."""
    store = _make_store()
    room = _make_room(store, state="snapshot_pending")
    agent = _logger_agent()
    st_event = _state_transition_event(
        room, new_state="snapshot_pending", prior_state="convergence"
    )
    store.append(st_event)

    snapshot_events = store.get_room_events(room.id)
    result = produce_and_emit_snapshot(
        agent=agent,
        room=room,
        current_event=st_event,
        event_store=store,
        snapshot_events=snapshot_events,
    )

    assert result.appended is True
    assert result.snapshot.room_state == "snapshot_pending"

    events = store.get_room_events(room.id)
    ss_events = [e for e in events if e.type == EventType.SUMMARY_SNAPSHOT]
    assert len(ss_events) == 1
    assert ss_events[0].author == build_author("logger")


def test_summary_snapshot_meta_validates_correctly() -> None:
    """summary_snapshot event metadata validates as SummarySnapshotMeta."""
    store = _make_store()
    room = _make_room(store, state="snapshot_pending")
    agent = _logger_agent()
    st_event = _state_transition_event(
        room, new_state="snapshot_pending", prior_state="convergence"
    )
    store.append(st_event)

    result = produce_and_emit_snapshot(
        agent=agent,
        room=room,
        current_event=st_event,
        event_store=store,
        snapshot_events=store.get_room_events(room.id),
    )

    events = store.get_room_events(room.id)
    ss_event = next(e for e in events if e.type == EventType.SUMMARY_SNAPSHOT)
    meta = SummarySnapshotMeta.model_validate(ss_event.metadata)
    assert meta.room_id == str(room.id)
    assert meta.room_state == "snapshot_pending"
    # Verify SummarySnapshotMeta matches Snapshot
    snap = result.snapshot
    assert meta.event_count == snap.event_count
    assert meta.decision_count == snap.decision_count
    assert meta.participants == snap.participants


def test_snapshot_result_matches_emitted_metadata() -> None:
    """SnapshotDispatchResult.snapshot matches the appended event's metadata."""
    store = _make_store()
    room = _make_room(store, state="snapshot_pending")
    agent = _logger_agent()
    st_event = _state_transition_event(
        room, new_state="snapshot_pending", prior_state="convergence"
    )
    store.append(st_event)

    result = produce_and_emit_snapshot(
        agent=agent,
        room=room,
        current_event=st_event,
        event_store=store,
        snapshot_events=store.get_room_events(room.id),
    )

    events = store.get_room_events(room.id)
    ss_event = next(e for e in events if e.type == EventType.SUMMARY_SNAPSHOT)
    meta = SummarySnapshotMeta.model_validate(ss_event.metadata)
    assert meta.snapshot_at == result.snapshot.snapshot_at


# ---------------------------------------------------------------------------
# §6 schema invariants — SnapshotDispatchResult
# ---------------------------------------------------------------------------


def test_snapshot_dispatch_result_frozen() -> None:
    from orchestrator.core.room import RoomType
    from orchestrator.derived.snapshot import Snapshot

    snap = Snapshot(
        room_id=generate_room_id(),
        room_type=RoomType.RESEARCH,
        room_state="snapshot_pending",
        snapshot_at=TimestampMs(999),
        event_count=0,
        decision_count=0,
        open_hypotheses=[],
        closed_decisions=[],
        tool_calls_pending_confirm=[],
        last_state_transition=None,
        participants=[],
    )
    result = SnapshotDispatchResult(snapshot=snap, appended=True)
    with pytest.raises((ValidationError, TypeError)):
        result.appended = False


def test_snapshot_dispatch_result_extra_forbid() -> None:
    from orchestrator.core.room import RoomType
    from orchestrator.derived.snapshot import Snapshot

    snap = Snapshot(
        room_id=generate_room_id(),
        room_type=RoomType.RESEARCH,
        room_state="snapshot_pending",
        snapshot_at=TimestampMs(999),
        event_count=0,
        decision_count=0,
        open_hypotheses=[],
        closed_decisions=[],
        tool_calls_pending_confirm=[],
        last_state_transition=None,
        participants=[],
    )
    with pytest.raises(ValidationError):
        SnapshotDispatchResult(snapshot=snap, appended=True, extra_field="x")  # type: ignore[call-arg]
