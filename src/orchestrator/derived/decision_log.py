"""Derived decision log: chronological filter over decision-class events.

Pure function; no LLM, no I/O, no event_store calls.
Constitutional invariant: test_constitution_no_llm_calls_in_derived_module.
See ADR-015 for shape locks + filter semantic + ordering invariants.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from orchestrator.core.event import Event, EventType, RejectionMeta, RetractionMeta, RoomId
from orchestrator.core.room import Room


class DecisionEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    event_type: Literal["decision", "decision_pivot", "rejection", "retraction"]
    timestamp: int
    author: str
    content_excerpt: str  # event.content[:200] verbatim per ADR-015 D3
    parent_event_id: str | None  # rejection.rejects / retraction.retracts; None for others


class DecisionLog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    room_id: RoomId
    entries: list[DecisionEntry]  # strict chronological by timestamp; ties by event_id lex


# D2 filter semantic: 4-event-type binary filter per ADR-015 D2.
_DECISION_FILTER: frozenset[EventType] = frozenset(
    {
        EventType.DECISION,
        EventType.DECISION_PIVOT,
        EventType.REJECTION,
        EventType.RETRACTION,
    }
)


def produce_decision_log(events: list[Event], room: Room) -> DecisionLog:
    """Pure derivation of chronological decision-class events. See ADR-015.

    Raises pydantic.ValidationError on malformed typed metadata per ADR-014 D7.
    """
    entries: list[DecisionEntry] = []
    for e in events:
        if e.type not in _DECISION_FILTER:
            continue

        parent_event_id: str | None = None
        if e.type == EventType.REJECTION:
            rej_meta = RejectionMeta.model_validate(e.metadata)
            parent_event_id = rej_meta.rejects
        elif e.type == EventType.RETRACTION:
            ret_meta = RetractionMeta.model_validate(e.metadata)
            parent_event_id = ret_meta.retracts

        entries.append(
            DecisionEntry(
                event_id=e.id,
                event_type=e.type.value,  # type: ignore[arg-type]
                timestamp=e.timestamp,
                author=e.author,
                content_excerpt=e.content[:200],
                parent_event_id=parent_event_id,
            )
        )

    # Sort by (timestamp, event_id) ascending per ADR-015 D4.
    # UUID v4 lex tie-break achieves per-set determinism (not insertion order);
    # acceptable for P1.6 scope per ADR-015 D4 rationale.
    entries.sort(key=lambda entry: (entry.timestamp, entry.event_id))

    return DecisionLog(room_id=room.id, entries=entries)
