"""End-to-end P2.2: Scenario Y — record → match → read → promote.

Per plan P2.2-4 acceptance criteria (ADR-017 D1-D6).

Exercises the full cross-room matcher flow:
  record_hypothesis (multiple rooms, varied tag surface forms) →
  run_matcher → candidate_for_promotion flags set →
  list_promotion_candidates → verified cluster surfaced →
  promote_hypothesis (flag is NOT a precondition; ADR-016 D3/D10) →
  assertions on orthogonality, idempotency, determinism.

Scenario structure:
  - room1: ["LLM Cost"]         }  same canonical {llm-cost} — cross-room cluster
  - room2: ["llm cost"]         }  (different surface forms, normalize-at-read payoff)
  - room3: ["ml-ops"]              singleton — 1 room
  - room1: ["solo topic"] + ["solo-topic"]  — same-room dup (distinct-row, not distinct-room)
  - room2, room3: topic_tags=[]    — untagged-across-rooms (A routing guard)

Source ≠ sink: record_hypothesis → hypothesis table (tags registered) →
               run_matcher → candidate_for_promotion flag →
               list_promotion_candidates → Hypothesis models →
               promote_hypothesis → verified_knowledge row
"""

from __future__ import annotations

import sqlite3

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
from orchestrator.memory.matcher import list_promotion_candidates, run_matcher
from orchestrator.memory.promotion import promote_hypothesis
from orchestrator.memory.schema import VKScope
from orchestrator.memory.store import (
    get_hypothesis_by_id,
    init_memory_schema,
    record_hypothesis,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return store, conn


def _make_room(store: EventStore, *, n_events: int = 2) -> tuple[Room, list[EventId]]:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    ids: list[EventId] = []
    base = now_ms()
    for i in range(n_events):
        evt = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.UTTERANCE,
            author="user",
            timestamp=TimestampMs(base + i),
            content=f"room {room.id[-4:]} event {i}",
        )
        store.append(evt)
        ids.append(evt.id)
    return room, ids


# ---------------------------------------------------------------------------
# Scenario Y
# ---------------------------------------------------------------------------


def test_scenario_y_cross_room_matcher_full_pipeline() -> None:
    """Scenario Y: full record → match → read → promote pipeline.

    AC#1-9 per plan P2.2-4.
    """
    store, conn = _make_store()

    room1, r1evts = _make_room(store, n_events=4)
    room2, r2evts = _make_room(store, n_events=4)
    room3, r3evts = _make_room(store, n_events=2)

    # --- Cluster: room1 + room2, different surface forms, same canonical {llm-cost} ---
    h_cluster_r1 = record_hypothesis(
        content="LLM costs are rising cross-room",
        room_id=room1.id,
        source_event_ids=[r1evts[0]],
        confidence=0.85,
        conn=conn,
        topic_tags=["LLM Cost"],  # stores "llm-cost"
    )
    h_cluster_r2 = record_hypothesis(
        content="llm cost observed in room2",
        room_id=room2.id,
        source_event_ids=[r2evts[0]],
        confidence=0.80,
        conn=conn,
        topic_tags=["llm cost"],  # different surface → same canonical "llm-cost"
    )

    # --- Singleton: room3, unique tag ---
    h_singleton = record_hypothesis(
        content="ml-ops claim from room3",
        room_id=room3.id,
        source_event_ids=[r3evts[0]],
        confidence=0.70,
        conn=conn,
        topic_tags=["ml-ops"],
    )

    # --- Same-room dup: two rows in room1, same canonical {solo-topic} ---
    h_sameroom_a = record_hypothesis(
        content="solo topic first version",
        room_id=room1.id,
        source_event_ids=[r1evts[1]],
        confidence=0.60,
        conn=conn,
        topic_tags=["solo topic"],  # canonical: "solo-topic"
    )
    h_sameroom_b = record_hypothesis(
        content="solo topic second version",
        room_id=room1.id,
        source_event_ids=[r1evts[2]],
        confidence=0.60,
        conn=conn,
        topic_tags=["solo-topic"],  # already canonical: "solo-topic"
    )

    # --- Untagged-across-rooms (A routing guard): room2 + room3, empty tags ---
    h_untagged_r2 = record_hypothesis(
        content="untagged claim in room2",
        room_id=room2.id,
        source_event_ids=[r2evts[1]],
        confidence=0.50,
        conn=conn,
        topic_tags=[],
    )
    h_untagged_r3 = record_hypothesis(
        content="untagged claim in room3",
        room_id=room3.id,
        source_event_ids=[r3evts[1]],
        confidence=0.50,
        conn=conn,
        topic_tags=[],
    )

    # --- Run matcher ---
    result = run_matcher(conn, min_rooms=2)

    # AC#3: llm-cost cluster flagged; singleton + same-room dup + untagged NOT flagged.
    for hyp_id in (h_cluster_r1.id, h_cluster_r2.id):
        loaded = get_hypothesis_by_id(hyp_id, conn=conn)
        assert loaded is not None
        assert loaded.candidate_for_promotion is True, f"{hyp_id}: llm-cost cluster must be flagged"

    for hyp_id in (
        h_singleton.id,
        h_sameroom_a.id,
        h_sameroom_b.id,
        h_untagged_r2.id,
        h_untagged_r3.id,
    ):
        loaded = get_hypothesis_by_id(hyp_id, conn=conn)
        assert loaded is not None
        assert loaded.candidate_for_promotion is False, (
            f"{hyp_id}: must NOT be flagged (singleton/same-room/untagged)"
        )

    # --- AC#4: list_promotion_candidates surfaces exactly the llm-cost cluster ---
    candidates = list_promotion_candidates(conn)
    candidate_ids = {c.id for c in candidates}
    assert h_cluster_r1.id in candidate_ids
    assert h_cluster_r2.id in candidate_ids
    assert len(candidates) == 2
    # Ordered id ASC.
    ids_list = [c.id for c in candidates]
    assert ids_list == sorted(ids_list)

    # --- AC#5: determinism — shuffled record order produces same flagged count ---
    store2, conn2 = _make_store()
    room1b, r1evtsb = _make_room(store2, n_events=2)
    room2b, r2evtsb = _make_room(store2, n_events=2)
    # Insert in reversed room order — shuffle proxy for scan-order independence.
    record_hypothesis(
        content="c2",
        room_id=room2b.id,
        source_event_ids=[r2evtsb[0]],
        confidence=0.8,
        conn=conn2,
        topic_tags=["llm cost"],
    )
    record_hypothesis(
        content="c1",
        room_id=room1b.id,
        source_event_ids=[r1evtsb[0]],
        confidence=0.8,
        conn=conn2,
        topic_tags=["LLM Cost"],
    )
    result2 = run_matcher(conn2, min_rooms=2)
    assert result2.rows_newly_flagged == result.rows_newly_flagged

    # --- AC#6: orthogonality — no VK rows, no decision events from matcher ---
    vk_count = conn.execute("SELECT COUNT(*) FROM verified_knowledge").fetchone()[0]
    assert vk_count == 0, "matcher must not insert VK rows"
    decision_count = conn.execute("SELECT COUNT(*) FROM events WHERE type = 'decision'").fetchone()[
        0
    ]
    assert decision_count == 0, "matcher must not emit decision events"

    # --- AC#6 cont: promote_hypothesis works on flagged AND un-flagged rows ---
    # Flagged row (llm-cost cluster, room1).
    vk_flagged = promote_hypothesis(
        h_cluster_r1.id,
        user_id="peidong",
        scope=VKScope.PERSONAL,
        topic_tags=["llm-cost"],
        event_store=store,
    )
    assert vk_flagged.content == h_cluster_r1.content
    # Un-flagged row (singleton, room3) — flag is NOT a precondition (ADR-016 D3/D10).
    vk_unflagged = promote_hypothesis(
        h_singleton.id,
        user_id="peidong",
        scope=VKScope.PERSONAL,
        topic_tags=["ml-ops"],
        event_store=store,
    )
    assert vk_unflagged.content == h_singleton.content

    # --- AC#7: idempotency --- second run flags nothing new ---
    result_r2 = run_matcher(conn, min_rooms=2)
    assert result_r2.rows_newly_flagged == 0

    # --- AC#8: min_rooms < 1 raises ValueError ---
    import pytest

    with pytest.raises(ValueError):
        run_matcher(conn, min_rooms=0)

    # --- Verify lookup still works after promotion ---
    results = lookup_verified_knowledge(["llm-cost"], VKScope.PERSONAL, conn=conn)
    assert len(results) == 1
    assert results[0].id == vk_flagged.id
