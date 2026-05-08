"""Tests for structural relation extraction (pure function) and the cache."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from orchestrator.core.event import (
    Event,
    EventId,
    EventNotFoundError,
    EventType,
    RelationType,
    RoomId,
    TimestampMs,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.relations import extract_structural_relations
from orchestrator.core.room import Room, RoomType

if TYPE_CHECKING:
    from .conftest import PopulatedFixture


def _event(
    event_type: EventType,
    *,
    parent_id: EventId | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: TimestampMs | None = None,
) -> Event:
    return Event(
        id=generate_event_id(),
        parent_id=parent_id,
        room_id=RoomId("room_x"),
        type=event_type,
        author="user",
        timestamp=timestamp if timestamp is not None else now_ms(),
        content="x",
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Pure function (no DB, no clock)
# ---------------------------------------------------------------------------


class TestExtractStructuralRelations:
    def test_root_event_no_relations(self) -> None:
        e = _event(EventType.USER_INPUT)
        assert extract_structural_relations(e) == []

    def test_replies_to_from_parent(self) -> None:
        parent_id = EventId("evt_parent")
        e = _event(EventType.UTTERANCE, parent_id=parent_id)
        rels = extract_structural_relations(e)
        assert len(rels) == 1
        assert rels[0].relation_type == RelationType.REPLIES_TO
        assert rels[0].target_event_id == parent_id

    def test_rejection_extracts_rejects(self) -> None:
        e = _event(
            EventType.REJECTION,
            parent_id=EventId("evt_parent"),
            metadata={"rejects": "evt_target", "reason": "bad"},
        )
        rels = extract_structural_relations(e)
        types = {r.relation_type for r in rels}
        assert types == {RelationType.REPLIES_TO, RelationType.REJECTS}
        rejects = next(r for r in rels if r.relation_type == RelationType.REJECTS)
        assert rejects.target_event_id == "evt_target"

    def test_retraction_extracts_retracts(self) -> None:
        e = _event(
            EventType.RETRACTION,
            metadata={"retracts": "evt_target", "reason": "wrong"},
        )
        rels = extract_structural_relations(e)
        assert len(rels) == 1
        assert rels[0].relation_type == RelationType.RETRACTS
        assert rels[0].target_event_id == "evt_target"

    def test_decision_extracts_based_on_per_item(self) -> None:
        e = _event(
            EventType.DECISION,
            metadata={"based_on": ["evt_a", "evt_b", "evt_c"]},
        )
        rels = extract_structural_relations(e)
        assert len(rels) == 3
        assert all(r.relation_type == RelationType.BASED_ON for r in rels)
        targets = {r.target_event_id for r in rels}
        assert targets == {"evt_a", "evt_b", "evt_c"}

    def test_decision_with_parent_combines(self) -> None:
        e = _event(
            EventType.DECISION,
            parent_id=EventId("evt_parent"),
            metadata={"based_on": ["evt_a"]},
        )
        rels = extract_structural_relations(e)
        types = [r.relation_type for r in rels]
        assert RelationType.REPLIES_TO in types
        assert RelationType.BASED_ON in types
        assert len(rels) == 2

    def test_pure_idempotent(self) -> None:
        """Pure: same Event in, same relations out, every time."""
        e = _event(
            EventType.DECISION,
            metadata={"based_on": ["evt_a", "evt_b"]},
        )
        r1 = extract_structural_relations(e)
        r2 = extract_structural_relations(e)
        assert r1 == r2

    def test_extracted_at_uses_event_timestamp(self) -> None:
        ts = TimestampMs(123_456_789)
        e = _event(
            EventType.UTTERANCE,
            parent_id=EventId("evt_p"),
            timestamp=ts,
        )
        rels = extract_structural_relations(e)
        assert all(r.extracted_at == ts for r in rels)

    def test_observation_only_replies_to(self) -> None:
        """Non-decision/rejection/retraction types only get replies_to."""
        e = _event(
            EventType.OBSERVATION,
            parent_id=EventId("evt_p"),
            metadata={"foo": "bar"},
        )
        rels = extract_structural_relations(e)
        assert len(rels) == 1
        assert rels[0].relation_type == RelationType.REPLIES_TO


# ---------------------------------------------------------------------------
# Cache: relations are persisted at append, queryable, recomputable.
# ---------------------------------------------------------------------------


class TestCachePersisted:
    def test_decision_relations_in_cache(self, populated_event_store: PopulatedFixture) -> None:
        store, ids = populated_event_store
        rels = store.get_relations_for(ids["decision"])
        types = {r.relation_type for r in rels}
        assert RelationType.REPLIES_TO in types  # parent=hypothesis
        assert RelationType.BASED_ON in types  # based_on=hypothesis

    def test_rejection_relations_in_cache(self, populated_event_store: PopulatedFixture) -> None:
        store, ids = populated_event_store
        rels = store.get_relations_for(ids["rejection"])
        types = {r.relation_type for r in rels}
        assert RelationType.REPLIES_TO in types
        assert RelationType.REJECTS in types

    def test_retraction_relations_in_cache(self, populated_event_store: PopulatedFixture) -> None:
        store, ids = populated_event_store
        rels = store.get_relations_for(ids["retraction"])
        types = {r.relation_type for r in rels}
        assert RelationType.REPLIES_TO in types
        assert RelationType.RETRACTS in types


class TestGetRelationsTo:
    def test_unfiltered(self, populated_event_store: PopulatedFixture) -> None:
        """All incoming edges to decision: 2 replies_to + 1 rejects + 1 retracts."""
        store, ids = populated_event_store
        incoming = store.get_relations_to(ids["decision"])
        types = [r.relation_type for r in incoming]
        assert types.count(RelationType.REPLIES_TO) == 2
        assert types.count(RelationType.REJECTS) == 1
        assert types.count(RelationType.RETRACTS) == 1

    def test_filtered_by_relation_type(self, populated_event_store: PopulatedFixture) -> None:
        store, ids = populated_event_store
        rejects = store.get_relations_to(ids["decision"], RelationType.REJECTS)
        assert len(rejects) == 1
        assert rejects[0].event_id == ids["rejection"]

    def test_ordered_by_extracted_at_desc(self, populated_event_store: PopulatedFixture) -> None:
        store, ids = populated_event_store
        replies = store.get_relations_to(ids["decision"], RelationType.REPLIES_TO)
        assert len(replies) == 2
        # Latest event first — retraction (ts offset 8) > rejection (ts offset 7).
        assert replies[0].extracted_at >= replies[1].extracted_at
        assert replies[0].event_id == ids["retraction"]


class TestRecomputeRelations:
    def test_recompute_idempotent(self, populated_event_store: PopulatedFixture) -> None:
        store, ids = populated_event_store
        before = sorted(
            store.get_relations_for(ids["rejection"]),
            key=lambda r: (r.relation_type.value, r.target_event_id),
        )
        store.recompute_relations(ids["rejection"])
        after = sorted(
            store.get_relations_for(ids["rejection"]),
            key=lambda r: (r.relation_type.value, r.target_event_id),
        )
        assert before == after

    def test_recompute_returns_count(self, populated_event_store: PopulatedFixture) -> None:
        store, ids = populated_event_store
        # rejection: 1 replies_to + 1 rejects = 2
        n = store.recompute_relations(ids["rejection"])
        assert n == 2

    def test_recompute_unknown_raises(self, in_memory_event_store: EventStore) -> None:
        with pytest.raises(EventNotFoundError):
            in_memory_event_store.recompute_relations(EventId("evt_x"))

    def test_recompute_all_idempotent(self, populated_event_store: PopulatedFixture) -> None:
        store, _ = populated_event_store
        n1 = store.recompute_all_relations()
        n2 = store.recompute_all_relations()
        assert n1 == n2

    def test_recompute_all_count(self, populated_event_store: PopulatedFixture) -> None:
        """8-node fixture relation breakdown:

        - 7 replies_to (events 2..8 each have a parent)
        - 1 based_on  (decision based_on hypothesis)
        - 1 rejects   (rejection rejects decision)
        - 1 retracts  (retraction retracts decision)
        - Total = 10
        """
        store, _ = populated_event_store
        assert store.recompute_all_relations() == 10


class TestMultipleRetractionsSameTarget:
    """Two retractions targeting the same event → both edges persist
    in the cache. Queries ordered by extracted_at DESC return the
    later retraction first."""

    def test_two_retractions(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)

        target = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.HYPOTHESIS,
            author="agent:operator",
            timestamp=TimestampMs(1000),
            content="thought",
            metadata={"confidence": 0.5},
        )
        store.append(target)

        r1 = Event(
            id=generate_event_id(),
            parent_id=target.id,
            room_id=room.id,
            type=EventType.RETRACTION,
            author="user",
            timestamp=TimestampMs(1001),
            content="never mind",
            metadata={
                "retracts": target.id,
                "reason": "first reconsideration",
            },
        )
        store.append(r1)

        r2 = Event(
            id=generate_event_id(),
            parent_id=target.id,
            room_id=room.id,
            type=EventType.RETRACTION,
            author="agent:skeptic",
            timestamp=TimestampMs(1002),
            content="agreed",
            metadata={
                "retracts": target.id,
                "reason": "skeptic agrees",
            },
        )
        store.append(r2)

        retracts = store.get_relations_to(target.id, RelationType.RETRACTS)
        assert len(retracts) == 2
        # extracted_at DESC → r2 (ts=1002) first.
        assert retracts[0].event_id == r2.id
        assert retracts[1].event_id == r1.id
