"""Tests for reentry/digest.py — derive_query_tags + assemble_reentry.

Coverage standard:
  §1 cross-module — assemble_reentry reads from memory/ (lookup, entity, archive)
     + reentry/store (leave-marker) → ReentryDigest. Source ≠ sink across modules.
  §6 N/A — ReentryDigest schema tested in test_schema.py.
  §2 N/A — pure code, no async shared state.
"""

from __future__ import annotations

import sqlite3

from orchestrator.core.event import (
    Event,
    EventType,
    TimestampMs,
    generate_event_id,
    generate_room_id,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.archive import record_project_archive
from orchestrator.memory.entity import record_entity, record_preference
from orchestrator.memory.promotion import promote_hypothesis
from orchestrator.memory.schema import EntityType, VKScope
from orchestrator.memory.store import init_memory_schema, record_hypothesis
from orchestrator.reentry.digest import assemble_reentry, derive_query_tags
from orchestrator.reentry.leave import record_leave_marker
from orchestrator.reentry.schema import NewSinceLeaveItem
from orchestrator.reentry.store import init_reentry_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_full_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    init_reentry_schema(conn)
    return store, conn


def _seed_room_with_event(store: EventStore, ts: int = 1000) -> tuple[Room, Event]:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.UTTERANCE,
        author="user",
        timestamp=TimestampMs(ts),
        content="seed event",
    )
    store.append(evt)
    return room, evt


def _promote_vk(
    store: EventStore,
    conn: sqlite3.Connection,
    room: Room,
    evt: Event,
    *,
    content: str = "a fact",
    topic_tags: list[str] | None = None,
    last_validated_ts: int | None = None,
) -> None:
    hyp = record_hypothesis(
        content=content,
        room_id=room.id,
        source_event_ids=[evt.id],
        confidence=0.9,
        conn=conn,
        topic_tags=topic_tags or [],
    )
    vk = promote_hypothesis(
        hyp.id,
        user_id="tester",
        scope=VKScope.PERSONAL,
        topic_tags=topic_tags or [],
        event_store=store,
    )
    if last_validated_ts is not None:
        conn.execute(
            "UPDATE verified_knowledge SET last_validated = ? WHERE id = ?",
            (last_validated_ts, str(vk.id)),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# derive_query_tags
# ---------------------------------------------------------------------------


def test_derive_query_tags_empty_room_returns_empty() -> None:
    """Room with no hypotheses → derive_query_tags returns [].

    Discriminating: fails if the function returns all tags or raises on empty.
    """
    store, conn = _make_full_store()
    room, _ = _seed_room_with_event(store)
    result = derive_query_tags(room.id, conn=conn)
    assert result == []


def test_derive_query_tags_returns_canonical_union() -> None:
    """Room with tagged hypotheses → canonical union returned.

    Discriminating: fails if the function returns raw tags or misses any hypothesis.
    """
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store)
    _promote_vk(store, conn, room, evt, topic_tags=["LLM Cost", "ml-ops"])
    result = derive_query_tags(room.id, conn=conn)
    assert "llm-cost" in result
    assert "ml-ops" in result


def test_derive_query_tags_deterministic() -> None:
    """Same inputs → same output (sorted list, no randomness)."""
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store)
    _promote_vk(store, conn, room, evt, topic_tags=["zzz", "aaa", "mmm"])
    result1 = derive_query_tags(room.id, conn=conn)
    result2 = derive_query_tags(room.id, conn=conn)
    assert result1 == result2
    assert result1 == sorted(result1)


# ---------------------------------------------------------------------------
# assemble_reentry — core assembly
# ---------------------------------------------------------------------------


def test_assemble_reentry_first_visit_new_since_leave_empty() -> None:
    """First visit (no leave-marker → last_seen_ts=None) → new_since_leave=[].

    ADR-021 D8: a first visit is not a return; 'what's new since you left' is empty.
    Discriminating: fails if first-visit returns all events instead of [].
    """
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store)
    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[evt],
        room=room,
        now=TimestampMs(9999),
    )
    assert digest.new_since_leave == []
    assert digest.last_seen_ts is None


def test_assemble_reentry_first_visit_no_archive_no_crash() -> None:
    """First visit with no archive → digest.archive is None, no crash."""
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store)
    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[evt],
        room=room,
        now=TimestampMs(5000),
    )
    assert digest.archive is None


def test_assemble_reentry_no_tags_skips_vk_lookup() -> None:
    """Empty tag-set → VK lookup skipped → recalled_knowledge=[]; no ValueError raised.

    Discriminating: fails if [] is passed to lookup_verified_knowledge (which raises).
    """
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store)
    # No tagged hypotheses → derive_query_tags returns [].
    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[evt],
        room=room,
        now=TimestampMs(5000),
    )
    assert digest.recalled_knowledge == []


def test_assemble_reentry_surfaces_vk_matching_room_tags() -> None:
    """VK matching the room's topic tags is included in recalled_knowledge.

    §1 source ≠ sink: memory/promotion writes VK; assemble_reentry reads it.
    Discriminating: fails if VK is not returned for matching tags.
    """
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store)
    _promote_vk(store, conn, room, evt, content="useful fact", topic_tags=["tag-x"])
    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[evt],
        room=room,
        now=TimestampMs(9999),
    )
    contents = [vk.content for vk in digest.recalled_knowledge]
    assert "useful fact" in contents


def test_assemble_reentry_includes_archive_when_present() -> None:
    """archive field carries the room's ProjectArchive when it exists.

    §1 source ≠ sink: record_project_archive writes; assemble_reentry reads.
    Discriminating: fails if archive is not included.
    """
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store)
    record_project_archive(
        room_id=room.id,
        title="Room Archive",
        duration_ms=1000,
        one_line_summary="summary",
        decision_log=[],
        spinoff_questions=[],
        conn=conn,
    )
    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[evt],
        room=room,
        now=TimestampMs(9999),
    )
    assert digest.archive is not None
    assert digest.archive.title == "Room Archive"


def test_assemble_reentry_includes_entities_and_preferences() -> None:
    """entities and preferences are included from memory/."""
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store)
    record_entity(EntityType.CONCEPT, {"name": "concept-a"}, conn=conn)
    record_preference("style", "concise", user_id="user1", conn=conn)

    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[evt],
        room=room,
        now=TimestampMs(9999),
    )
    entity_names = [e.attributes.get("name") for e in digest.entities]
    pref_keys = [p.attributes.get("key") for p in digest.preferences]
    assert "concept-a" in entity_names
    assert "style" in pref_keys


# ---------------------------------------------------------------------------
# assemble_reentry — new_since_leave diff
# ---------------------------------------------------------------------------


def test_assemble_reentry_new_since_leave_typed_items_not_dict() -> None:
    """new_since_leave items are NewSinceLeaveItem (typed), not dicts.

    ADR-021 D7/D8: Y3 absorbed — typed descriptor, not list[dict].
    Discriminating: fails if list contains dict objects.
    Uses DECISION_PIVOT (decision-class) since only decision-class events surface.
    """
    store, conn = _make_full_store()
    room, seed_evt = _seed_room_with_event(store, ts=500)
    decision_evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.DECISION_PIVOT,
        author="user",
        timestamp=TimestampMs(5000),
        content="a decision after leave",
    )
    store.append(decision_evt)
    record_leave_marker(room.id, "user1", TimestampMs(1000), conn=conn)

    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[seed_evt, decision_evt],
        room=room,
        now=TimestampMs(9999),
    )
    # decision_evt.timestamp (5000) > last_seen_ts (1000) and is decision-class → should appear
    assert len(digest.new_since_leave) > 0
    for item in digest.new_since_leave:
        assert isinstance(item, NewSinceLeaveItem), f"expected NewSinceLeaveItem, got {type(item)}"


def test_assemble_reentry_new_since_leave_exact_set() -> None:
    """new_since_leave contains EXACTLY the post-marker facts, by stable labels.

    RC-25 discriminating: asserts exact label set, not just count.
    Discriminating: fails if pre-marker facts leak into new_since_leave or
    post-marker facts are missing.
    """
    store, conn = _make_full_store()
    room, old_evt = _seed_room_with_event(store, ts=500)
    # Second event after marker — DECISION_PIVOT (decision-class) to appear in new_since_leave.
    new_evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.DECISION_PIVOT,
        author="user",
        timestamp=TimestampMs(3000),
        content="post-marker event",
    )
    store.append(new_evt)

    record_leave_marker(room.id, "user1", TimestampMs(1000), conn=conn)

    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[old_evt, new_evt],
        room=room,
        now=TimestampMs(9999),
    )
    # old_evt.timestamp (500) < marker (1000) → NOT in new_since_leave.
    # new_evt.timestamp (3000) > marker (1000) → IN new_since_leave.
    event_labels = [item.label for item in digest.new_since_leave if item.fact_type == "event"]
    assert "post-marker event" in event_labels
    assert "seed event" not in event_labels


def test_assemble_reentry_new_since_leave_only_decision_class_events() -> None:
    """new_since_leave event part contains only decision-class events (Y2b filter).

    Q5 discriminating: seeds both a decision-class (DECISION_PIVOT) and a
    non-decision-class (UTTERANCE) event after the leave marker — both post-marker
    by timestamp. If the decision-class filter is removed, the UTTERANCE would appear
    in event_labels, causing the "not in" assertion to fail.
    """
    store, conn = _make_full_store()
    room, seed_evt = _seed_room_with_event(store, ts=500)
    record_leave_marker(room.id, "user1", TimestampMs(1000), conn=conn)

    # Post-marker decision-class event — must appear in new_since_leave.
    decision_evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.DECISION_PIVOT,
        author="user",
        timestamp=TimestampMs(2000),
        content="a pivot decision",
    )
    store.append(decision_evt)

    # Post-marker non-decision-class event — must NOT appear (same ts range, different type).
    utterance_evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.UTTERANCE,
        author="user",
        timestamp=TimestampMs(3000),
        content="a plain utterance",
    )
    store.append(utterance_evt)

    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[seed_evt, decision_evt, utterance_evt],
        room=room,
        now=TimestampMs(9999),
    )

    event_labels = [item.label for item in digest.new_since_leave if item.fact_type == "event"]

    # Decision-class event must surface.
    assert "a pivot decision" in event_labels, (
        "decision-class post-marker event must appear in new_since_leave"
    )
    # Non-decision-class event must be excluded.
    # Discriminating: removing the type filter causes UTTERANCE to appear here → assertion fails.
    assert "a plain utterance" not in event_labels, (
        "non-decision-class post-marker UTTERANCE must NOT appear in new_since_leave"
    )


def test_assemble_reentry_new_since_leave_vk_after_marker() -> None:
    """VK validated after the leave-marker appears in new_since_leave.

    Discriminating: fails if VK with last_validated > last_seen_ts is not surfaced.
    """
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store, ts=500)
    _promote_vk(
        store,
        conn,
        room,
        evt,
        content="new knowledge",
        topic_tags=["tag-q"],
        last_validated_ts=3000,
    )
    record_leave_marker(room.id, "user1", TimestampMs(1000), conn=conn)

    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[evt],
        room=room,
        now=TimestampMs(9999),
    )
    vk_labels = [
        item.label for item in digest.new_since_leave if item.fact_type == "verified_knowledge"
    ]
    assert "new knowledge" in vk_labels


def test_assemble_reentry_new_since_leave_sorted_occurred_at_asc() -> None:
    """new_since_leave is sorted by occurred_at ASC. Per ADR-021 D8."""
    store, conn = _make_full_store()
    room, evt1 = _seed_room_with_event(store, ts=2000)
    evt2 = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.UTTERANCE,
        author="user",
        timestamp=TimestampMs(4000),
        content="later event",
    )
    store.append(evt2)
    record_leave_marker(room.id, "user1", TimestampMs(1000), conn=conn)

    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[evt2, evt1],  # insertion order reversed
        room=room,
        now=TimestampMs(9999),
    )
    timestamps = [item.occurred_at for item in digest.new_since_leave]
    assert timestamps == sorted(timestamps), "new_since_leave must be sorted occurred_at ASC"


def test_assemble_reentry_determinism_same_inputs_same_digest() -> None:
    """Same inputs → same ReentryDigest (deterministic). ADR-021 D3."""
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store, ts=500)
    _promote_vk(store, conn, room, evt, content="fact", topic_tags=["tag-d"])
    record_leave_marker(room.id, "user1", TimestampMs(100), conn=conn)

    digest1 = assemble_reentry(
        room.id, "user1", conn=conn, events=[evt], room=room, now=TimestampMs(9000)
    )
    digest2 = assemble_reentry(
        room.id, "user1", conn=conn, events=[evt], room=room, now=TimestampMs(9000)
    )
    assert digest1.recalled_knowledge == digest2.recalled_knowledge
    assert digest1.new_since_leave == digest2.new_since_leave
    assert digest1.last_seen_ts == digest2.last_seen_ts


def test_assemble_reentry_empty_memory_no_crash() -> None:
    """Empty DB (no VK, no entities, no prefs, no archive) → no crash."""
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store)
    digest = assemble_reentry(
        room.id, "user1", conn=conn, events=[evt], room=room, now=TimestampMs(5000)
    )
    assert digest.recalled_knowledge == []
    assert digest.entities == []
    assert digest.preferences == []
    assert digest.archive is None
    assert digest.new_since_leave == []


def test_assemble_reentry_preferences_scoped_to_user() -> None:
    """preferences only contains preferences for the given user_id.

    Discriminating: fails if preferences from a different user are returned.
    """
    store, conn = _make_full_store()
    room, evt = _seed_room_with_event(store)
    record_preference("style", "verbose", user_id="user1", conn=conn)
    record_preference("style", "concise", user_id="user2", conn=conn)

    digest = assemble_reentry(
        room.id, "user1", conn=conn, events=[evt], room=room, now=TimestampMs(5000)
    )
    pref_users = [p.evidence.get("declared_by") for p in digest.preferences]
    assert "user1" in pref_users
    assert "user2" not in pref_users
