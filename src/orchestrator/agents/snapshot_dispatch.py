"""Snapshot dispatch: produce-and-emit snapshot on Logger trigger.

Sibling to agents/tool_dispatch.py per ADR-013 D1 separate-concern pattern.
Called by dispatch.py when agent.id == "logger" and current_event is a
state_transition to snapshot_pending.

Layering: imports from derived/, core/event, core/event_store, agents/schema only.
No LLM imports — snapshot production is code-decided per Principle 5 + ADR-014 D1.
Constitutional invariant: test_constitution_no_llm_calls_in_agents_module.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from orchestrator.agents.schema import Agent
from orchestrator.core.event import (
    Event,
    EventType,
    SummarySnapshotMeta,
    build_author,
    generate_event_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room
from orchestrator.derived.decision_log import produce_decision_log
from orchestrator.derived.snapshot import Snapshot, produce_snapshot


class SnapshotDispatchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot: Snapshot
    appended: bool


def produce_and_emit_snapshot(
    agent: Agent,
    room: Room,
    current_event: Event,
    event_store: EventStore,
    snapshot_events: list[Event],
) -> SnapshotDispatchResult:
    """Produce snapshot + decision-log and append summary_snapshot event.

    Clock-injection per ADR-014 D1 + D6: caller owns wall-clock impurity.
    snapshot_at is captured once here and threaded through to produce_snapshot
    AND used as the appended event's timestamp — consistent caller-frozen-time.

    Returns SnapshotDispatchResult with the produced Snapshot and appended=True.
    """
    snapshot_at = now_ms()
    snapshot = produce_snapshot(snapshot_events, room, snapshot_at=snapshot_at)

    # Decision log is derived and available to callers via event_store, not persisted.
    # Produce here to exercise the derivation; result not stored (ADR-015 D5).
    _ = produce_decision_log(snapshot_events, room)

    meta = SummarySnapshotMeta.model_validate(snapshot.model_dump())
    event_store.append(
        Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.SUMMARY_SNAPSHOT,
            author=build_author(agent.id),
            timestamp=snapshot_at,
            content="",
            metadata=meta.model_dump(),
        )
    )
    return SnapshotDispatchResult(snapshot=snapshot, appended=True)
