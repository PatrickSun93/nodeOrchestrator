"""End-to-end P2.1: record → register → promote → lookup (shared tag registry).

Per plan P2.1-6 acceptance criteria (ADR-018 §Decisions):
  - record_hypothesis with topic_tags → tag registered + hypothesis stores canonical
  - promote_hypothesis carries canonical tags into VK (same vocabulary)
  - lookup_verified_knowledge (different surface form) hits the VK
  - Cross-room consistency: two hypotheses from different rooms with semantically
    equivalent tags resolve to the SAME canonical form

Source ≠ sink invariant:
  record_hypothesis (room1) →
  tag table (registry) + hypothesis.topic_tags (canonical) →
  promote_hypothesis →
  verified_knowledge.topic_tags (canonical, same vocabulary) →
  lookup_verified_knowledge (non-canonical query) → VK found cross-room
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
    event_ids: list[EventId] = []
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
        event_ids.append(evt.id)
    return room, event_ids


# ---------------------------------------------------------------------------
# Scenario P2.1 — full record → register → promote → lookup e2e
# ---------------------------------------------------------------------------


def test_p2_1_full_pipeline_record_to_lookup() -> None:
    """Scenario P2.1: tag registry end-to-end.

    1. record_hypothesis(room1, topic_tags=["LLM Cost"])
       → tag "llm-cost" registered, hypothesis stores ["llm-cost"]
    2. promote_hypothesis carries canonical tags into VK
    3. lookup_verified_knowledge(["llm cost"]) (different surface form) hits the VK
    4. Cross-room: hypothesis in room2 with topic_tags=["llm cost"] resolves
       to the same canonical "llm-cost" — the registry's load-bearing property
    """
    store, conn = _make_store()

    room1, room1_events = _make_room(store, n_events=2)
    room2, room2_events = _make_room(store, n_events=2)

    # Step 1: record in room1 with raw tag "LLM Cost".
    hyp1 = record_hypothesis(
        content="LLMs have cost implications across rooms",
        room_id=room1.id,
        source_event_ids=room1_events,
        confidence=0.85,
        conn=conn,
        topic_tags=["LLM Cost"],
    )
    assert hyp1.topic_tags == ["llm-cost"]

    # Tag is registered in the tag table.
    tag_row = conn.execute("SELECT canonical FROM tag WHERE canonical = 'llm-cost'").fetchone()
    assert tag_row is not None, "tag 'llm-cost' must be registered after record_hypothesis"

    # Step 1b: cross-room consistency — room2 hypothesis with "llm cost" (different
    # surface form) resolves to the SAME canonical "llm-cost".
    hyp2 = record_hypothesis(
        content="LLM cost is relevant cross-room",
        room_id=room2.id,
        source_event_ids=room2_events,
        confidence=0.75,
        conn=conn,
        topic_tags=["llm cost"],  # different surface form, same canonical
    )
    assert hyp2.topic_tags == ["llm-cost"], (
        "room2 hypothesis must resolve 'llm cost' to the same 'llm-cost' canonical"
    )

    # Only one canonical tag in the registry (dedup cross-room).
    tag_count = conn.execute("SELECT COUNT(*) FROM tag WHERE canonical = 'llm-cost'").fetchone()[0]
    assert tag_count == 1, "shared canonical vocabulary: same tag must not be registered twice"

    # Step 2: promote hyp1 → VK carries canonical tags.
    vk = promote_hypothesis(
        hyp1.id,
        user_id="peidong",
        scope=VKScope.PERSONAL,
        topic_tags=["LLM Cost"],  # raw form; resolved to canonical inside promotion
        event_store=store,
    )
    assert vk.topic_tags == ["llm-cost"], "VK must store canonical tags (same vocabulary)"
    assert vk.promoted_from_hypothesis_id == hyp1.id

    # Hypothesis status updated.
    reloaded_hyp1 = get_hypothesis_by_id(hyp1.id, conn=conn)
    assert reloaded_hyp1 is not None
    assert reloaded_hyp1.topic_tags == ["llm-cost"]

    # Step 3: lookup from room2 context with different surface form.
    results = lookup_verified_knowledge(["llm cost"], VKScope.PERSONAL, conn=conn)
    assert len(results) == 1, "lookup must find the promoted VK via both-sides normalization"
    assert results[0].id == vk.id
    assert results[0].topic_tags == ["llm-cost"]
    assert results[0].content == "LLMs have cost implications across rooms"


def test_p2_1_no_llm_constitution() -> None:
    """Constitution: no LLM calls in any memory/ module (tags.py auto-covered)."""
    from pathlib import Path

    memory_dir = Path("src/orchestrator/memory")
    for py_file in memory_dir.rglob("*.py"):
        source = py_file.read_text()
        assert "LLMPurpose" not in source or "content-gen" in source, (
            f"{py_file}: LLMPurpose usage in memory/ must be content-gen only"
        )
        assert "anthropic" not in source.lower() or "ADR" in source, (
            f"{py_file}: direct anthropic SDK import not allowed in memory/"
        )
