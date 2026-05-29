"""End-to-end Scenario X: 3-room promotion → cross-room lookup.

Load-bearing acceptance per senior plan §2 P1.6.5-5 + brief architect-settled #8.

Exercises the cross-room memory persistence flow:
  record_hypothesis (room1) →
  record_hypothesis (room2) →
  promote_hypothesis (room1's hypothesis) →
  lookup_verified_knowledge (room3 context) →
  assertions on round-trip, promotion event, atomicity sub-test.

Source ≠ sink invariant:
  record_hypothesis → SQLite hypothesis row →
  promote_hypothesis → SQLite VK row + event_store decision event →
  lookup_verified_knowledge → VK row returned cross-room.
"""

from __future__ import annotations

import sqlite3

import pytest

from orchestrator.core.event import (
    Event,
    EventId,
    EventType,
    TimestampMs,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.lookup import lookup_verified_knowledge
from orchestrator.memory.promotion import promote_hypothesis
from orchestrator.memory.schema import HypothesisStatus, VKScope
from orchestrator.memory.store import (
    get_hypothesis_by_id,
    init_memory_schema,
    record_hypothesis,
)

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _make_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return store, conn


def _make_room(store: EventStore, *, n_events: int = 3) -> tuple[Room, list[EventId]]:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    event_ids = []
    base = now_ms()
    for i in range(n_events):
        evt = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.UTTERANCE if i > 0 else EventType.USER_INPUT,
            author="user" if i == 0 else "agent:operator",
            timestamp=TimestampMs(base + i),
            content=f"Room {room.id[-4:]} event {i}",
        )
        store.append(evt)
        event_ids.append(evt.id)
    return room, event_ids


# ---------------------------------------------------------------------------
# Scenario X — full 3-room flow
# ---------------------------------------------------------------------------


def test_scenario_x_3_room_promotion_to_query() -> None:
    """Scenario X: 3 Research rooms. Hypothesis promoted in room1; room3 finds the VK.

    Steps per brief architect-settled #8:
    1. Init event store + memory schema on one SQLite connection.
    2. Create 3 Research rooms with synthetic event streams.
    3. record_hypothesis in room1 and room2 (same content).
    4. Synthetically set candidate_for_promotion=True on both rows
       (matcher deferred to P1.7+).
    5. promote_hypothesis(hyp1, user_id='peidong', scope=VKScope.PERSONAL,
       topic_tags=['claim-x'], event_store=store).
    6. lookup_verified_knowledge(['claim-x'], VKScope.PERSONAL, conn=conn)
       from room3 context.
    7. Assertions: round-trip, promotion event, status, cross-room.
    """
    store, conn = _make_store()

    # Step 2: 3 Research rooms, each with 3 events.
    room1, room1_events = _make_room(store, n_events=3)
    room2, room2_events = _make_room(store, n_events=3)
    _room3, _room3_events = _make_room(store, n_events=3)

    # Step 3: record hypotheses in room1 and room2.
    hyp1 = record_hypothesis(
        content="claim X: the layered architecture is correct",
        room_id=room1.id,
        source_event_ids=room1_events[:2],
        confidence=0.7,
        conn=conn,
    )
    hyp2 = record_hypothesis(
        content="claim X: the layered architecture is correct",  # same content
        room_id=room2.id,
        source_event_ids=room2_events[:2],
        confidence=0.75,
        conn=conn,
    )

    # Step 4 (bypass): synthetically set candidate_for_promotion=True on both.
    conn.execute(
        "UPDATE hypothesis SET candidate_for_promotion = 1 WHERE id IN (?, ?)",
        (str(hyp1.id), str(hyp2.id)),
    )
    conn.commit()

    # Step 5: promote hyp1.
    vk1 = promote_hypothesis(
        hyp1.id,
        user_id="peidong",
        scope=VKScope.PERSONAL,
        topic_tags=["claim-x"],
        event_store=store,
    )

    # Step 6: room3 lookups verified knowledge.
    results = lookup_verified_knowledge(["claim-x"], VKScope.PERSONAL, conn=conn)

    # Step 7: assertions.

    # 7a: exactly 1 VK in results.
    assert len(results) == 1
    found_vk = results[0]

    # 7b: round-trip (vk1 ID matches the returned VK).
    assert found_vk.id == vk1.id

    # 7c: promoted_from_hypothesis_id and promoted_by_user_id.
    assert found_vk.promoted_from_hypothesis_id == hyp1.id
    assert found_vk.promoted_by_user_id == "peidong"

    # 7d: promotion event present in event_store.
    promo_event = store.get_event(vk1.promotion_event_id)
    assert promo_event is not None
    assert promo_event.type == EventType.DECISION
    assert promo_event.metadata["promotion"] is True
    assert promo_event.metadata["hypothesis_id"] == str(hyp1.id)
    assert promo_event.metadata["vk_id"] == str(vk1.id)

    # 7e: promotion event room_id = room1.id (originating hypothesis room, ADR-016 D3).
    assert str(promo_event.room_id) == str(room1.id)

    # 7f: hyp1 status = VERIFIED; hyp2 status = PENDING (untouched).
    reloaded_hyp1 = get_hypothesis_by_id(hyp1.id, conn=conn)
    reloaded_hyp2 = get_hypothesis_by_id(hyp2.id, conn=conn)
    assert reloaded_hyp1 is not None
    assert reloaded_hyp2 is not None
    assert reloaded_hyp1.status == HypothesisStatus.VERIFIED
    assert reloaded_hyp2.status == HypothesisStatus.PENDING

    # 7g: source ≠ sink invariant: vk1.promotion_event_id == promo_event.id.
    assert vk1.promotion_event_id == promo_event.id

    # 7h: cross-room semantics — room3 finds VK from room1 promotion.
    assert str(found_vk.promoted_from_hypothesis_id) == str(hyp1.id)
    # room3 has no hypothesis rows, but the VK is accessible via lookup.
    assert found_vk.scope == VKScope.PERSONAL


def test_scenario_x_atomicity_sub_test() -> None:
    """Atomicity sub-test: VK INSERT failure rolls back the promotion event.

    Separate test function per plan P1.6.5-5 acceptance. Uses the UNIQUE
    constraint pre-insert technique (same as test_promotion.py atomicity test 1).
    """

    store, conn = _make_store()
    room1, room1_events = _make_room(store, n_events=3)

    hyp1 = record_hypothesis(
        content="atomicity test hypothesis",
        room_id=room1.id,
        source_event_ids=room1_events[:2],
        confidence=0.6,
        conn=conn,
    )

    # Pre-insert a fake VK with same promoted_from_hypothesis_id → UNIQUE violation.
    conn.execute(
        """INSERT INTO verified_knowledge
               (id, content, topic_tags, evidence, last_validated,
                contradictions, scope, promoted_from_hypothesis_id,
                promoted_by_user_id, promotion_event_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "vk_" + "e" * 32, "fake", "[]", "{}", 1, "[]", "personal",
            str(hyp1.id),           # collision
            "fake_user", str(room1_events[0]),  # existing event FK
        ),
    )
    conn.commit()

    # Promotion should fail with IntegrityError (UNIQUE violation at VK INSERT).
    with pytest.raises(sqlite3.IntegrityError):
        promote_hypothesis(
            hyp1.id,
            user_id="peidong",
            scope=VKScope.PERSONAL,
            topic_tags=["atomicity"],
            event_store=store,
        )

    # Decision event NOT in event_store (rolled back).
    decision_count = conn.execute(
        "SELECT COUNT(*) FROM events WHERE type = 'decision'"
    ).fetchone()[0]
    assert decision_count == 0, "decision event must be rolled back"

    # hyp1 status still PENDING.
    reloaded = get_hypothesis_by_id(hyp1.id, conn=conn)
    assert reloaded is not None
    assert reloaded.status == HypothesisStatus.PENDING
