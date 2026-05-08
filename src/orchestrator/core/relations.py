"""Structural relation extraction (pure function).

Used on both the write path (`EventStore.append`) and the recompute path
(`EventStore.recompute_relations` / `recompute_all_relations`). Same
input, same output, no I/O, no clock dependency. Per handoff.md §3.1
this is decision-path code, not LLM output.

P0 extracts four structural relations:

  * `replies_to` — from `event.parent_id` (if not None).
  * `rejects`    — from `event.metadata['rejects']`  when type=REJECTION.
  * `retracts`   — from `event.metadata['retracts']` when type=RETRACTION.
  * `based_on`   — from `event.metadata['based_on'][i]` when type=DECISION,
                   one edge per item.

Semantic relations (`supersedes`, `derives_from`, `related_to`) require
LLM suggestion + explicit human confirmation; out of P0 scope.
"""

from __future__ import annotations

from orchestrator.core.event import (
    Event,
    EventId,
    EventType,
    Relation,
    RelationType,
)


def extract_structural_relations(event: Event) -> list[Relation]:
    """Pure: given an Event, return the structural Relation edges it implies.

    The function is total: it never raises for a valid Event. It does
    not look up the targets in storage — referential integrity is the
    write path's concern (FK constraints + write-time validation),
    not this function's.

    `Relation.extracted_at` is set to `event.timestamp` (NOT wall-clock
    at extraction time) so that recomputing the cache produces edges
    with the same `extracted_at` as the original write — useful for
    "latest by event time" queries to be stable across rebuilds.

    Returns:
        List of Relation. Empty if the event implies no edges (a root
        event with no `parent_id` and no metadata-cited targets).
    """
    relations: list[Relation] = []
    extracted_at = event.timestamp

    # 1. replies_to — from parent_id (any event type).
    if event.parent_id is not None:
        relations.append(
            Relation(
                event_id=event.id,
                relation_type=RelationType.REPLIES_TO,
                target_event_id=event.parent_id,
                extracted_at=extracted_at,
            )
        )

    # 2-4. type-specific edges from metadata.
    if event.type == EventType.REJECTION:
        target = event.metadata.get("rejects")
        if target is not None:
            relations.append(
                Relation(
                    event_id=event.id,
                    relation_type=RelationType.REJECTS,
                    target_event_id=EventId(target),
                    extracted_at=extracted_at,
                )
            )
    elif event.type == EventType.RETRACTION:
        target = event.metadata.get("retracts")
        if target is not None:
            relations.append(
                Relation(
                    event_id=event.id,
                    relation_type=RelationType.RETRACTS,
                    target_event_id=EventId(target),
                    extracted_at=extracted_at,
                )
            )
    elif event.type == EventType.DECISION:
        for target in event.metadata.get("based_on", []):
            relations.append(
                Relation(
                    event_id=event.id,
                    relation_type=RelationType.BASED_ON,
                    target_event_id=EventId(target),
                    extracted_at=extracted_at,
                )
            )

    return relations
