"""Tests for memory/lookup.py — lookup_verified_knowledge + list_room_topic_tags.

Per plan P1.6.5-4 acceptance:
  - scope filter, topic_tags OR-semantics, empty topic_tags ValueError,
    ordering last_validated DESC + tie-break id ASC, cross-room inclusion,
    no LLM call (constitutional test stays green).

P2.5-2 addition: list_room_topic_tags — deterministic tag-union per room.
"""

from __future__ import annotations

import sqlite3

import pytest

from orchestrator.core.event import TimestampMs, generate_event_id, generate_room_id
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.lookup import list_room_topic_tags, lookup_verified_knowledge
from orchestrator.memory.promotion import promote_hypothesis
from orchestrator.memory.schema import VKScope
from orchestrator.memory.store import init_memory_schema, record_hypothesis

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_full_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return store, conn


def _seed_and_promote(
    store: EventStore,
    conn: sqlite3.Connection,
    *,
    content: str = "claim",
    topic_tags: list[str] | None = None,
    scope: VKScope = VKScope.PERSONAL,
    last_validated_ts: int | None = None,
) -> None:
    from orchestrator.core.event import Event, EventType, now_ms

    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.UTTERANCE,
        author="user",
        timestamp=TimestampMs(now_ms()),
        content="msg",
    )
    store.append(evt)
    hyp = record_hypothesis(
        content=content,
        room_id=room.id,
        source_event_ids=[evt.id],
        confidence=0.8,
        conn=conn,
    )
    vk = promote_hypothesis(
        hyp.id,
        user_id="peidong",
        scope=scope,
        topic_tags=topic_tags,
        event_store=store,
    )
    # Override last_validated if requested (for ordering tests).
    if last_validated_ts is not None:
        conn.execute(
            "UPDATE verified_knowledge SET last_validated = ? WHERE id = ?",
            (last_validated_ts, str(vk.id)),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLookupVerifiedKnowledge:
    def test_empty_topic_tags_raises(self) -> None:
        _store, conn = _make_full_store()
        with pytest.raises(ValueError, match="topic_tags must be non-empty"):
            lookup_verified_knowledge([], VKScope.PERSONAL, conn=conn)

    def test_scope_filter(self) -> None:
        store, conn = _make_full_store()
        _seed_and_promote(
            store, conn, content="personal", topic_tags=["tag-a"], scope=VKScope.PERSONAL
        )
        _seed_and_promote(store, conn, content="team", topic_tags=["tag-a"], scope=VKScope.TEAM)
        results = lookup_verified_knowledge(["tag-a"], VKScope.PERSONAL, conn=conn)
        assert len(results) == 1
        assert results[0].content == "personal"

    def test_topic_tags_or_semantics(self) -> None:
        store, conn = _make_full_store()
        _seed_and_promote(store, conn, content="tag-a only", topic_tags=["tag-a"])
        _seed_and_promote(store, conn, content="tag-b only", topic_tags=["tag-b"])
        _seed_and_promote(store, conn, content="tag-c only", topic_tags=["tag-c"])
        results = lookup_verified_knowledge(["tag-a", "tag-b"], VKScope.PERSONAL, conn=conn)
        contents = {r.content for r in results}
        assert "tag-a only" in contents
        assert "tag-b only" in contents
        assert "tag-c only" not in contents

    def test_no_match_returns_empty(self) -> None:
        store, conn = _make_full_store()
        _seed_and_promote(store, conn, topic_tags=["tag-a"])
        results = lookup_verified_knowledge(["tag-z"], VKScope.PERSONAL, conn=conn)
        assert results == []

    def test_ordering_last_validated_desc(self) -> None:
        store, conn = _make_full_store()
        _seed_and_promote(store, conn, content="oldest", topic_tags=["t"], last_validated_ts=1000)
        _seed_and_promote(store, conn, content="newest", topic_tags=["t"], last_validated_ts=3000)
        _seed_and_promote(store, conn, content="middle", topic_tags=["t"], last_validated_ts=2000)
        results = lookup_verified_knowledge(["t"], VKScope.PERSONAL, conn=conn)
        assert len(results) == 3
        assert results[0].last_validated == 3000
        assert results[1].last_validated == 2000
        assert results[2].last_validated == 1000

    def test_cross_room_results_included(self) -> None:
        """VKs from different originating rooms all appear in lookup results."""
        store, conn = _make_full_store()
        _seed_and_promote(store, conn, content="room1-claim", topic_tags=["cross"])
        _seed_and_promote(store, conn, content="room2-claim", topic_tags=["cross"])
        results = lookup_verified_knowledge(["cross"], VKScope.PERSONAL, conn=conn)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# D6 refinement — both-sides normalization (P2.1-5, ADR-018 D7)
# ---------------------------------------------------------------------------


class TestLookupBothSidesNormalization:
    def test_non_canonical_query_hits_canonical_stored_tag(self) -> None:
        """ADR-018 D7 AC#2: query "LLM Cost" hits VK stored canonical "llm-cost"."""
        store, conn = _make_full_store()
        _seed_and_promote(store, conn, content="canonical stored", topic_tags=["llm-cost"])
        results = lookup_verified_knowledge(["LLM Cost"], VKScope.PERSONAL, conn=conn)
        assert len(results) == 1
        assert results[0].content == "canonical stored"

    def test_legacy_raw_stored_row_found_by_normalized_query(self) -> None:
        """ADR-018 D7 AC#3: legacy raw-stored topic_tags found via both-sides normalization.

        Simulates a pre-P2.1 VK row with un-normalized stored tags (never
        through resolve_tags). Both-sides normalization makes it findable
        without backfill (ADR-018 D8).
        """
        import json as _json

        from orchestrator.core.event import (
            Event,
            EventType,
            TimestampMs,
            generate_event_id,
            now_ms,
        )
        from orchestrator.core.room import Room, RoomType
        from orchestrator.memory.schema import generate_vk_id
        from orchestrator.memory.store import record_hypothesis

        store, conn = _make_full_store()
        _seed_and_promote(store, conn, content="canonical-row", topic_tags=["llm-cost"])

        # Directly insert a legacy raw-stored VK row (simulates pre-P2.1).
        room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
        store.append_room(room)
        evt = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.UTTERANCE,
            author="user",
            timestamp=TimestampMs(now_ms()),
            content="legacy",
        )
        store.append(evt)

        hyp = record_hypothesis(
            content="legacy hypothesis",
            room_id=room.id,
            source_event_ids=[evt.id],
            confidence=0.8,
            conn=conn,
        )
        fake_vk_id = generate_vk_id()
        fake_event_id = generate_event_id()
        store.append(
            Event(
                id=fake_event_id,
                room_id=room.id,
                type=EventType.UTTERANCE,  # any valid event type satisfies the FK
                author="system",
                timestamp=TimestampMs(now_ms() + 1),
                content="legacy promotion marker",
            )
        )
        conn.execute("UPDATE hypothesis SET status = 'verified' WHERE id = ?", (str(hyp.id),))
        conn.execute(
            """INSERT INTO verified_knowledge
                   (id, content, topic_tags, evidence, last_validated,
                    contradictions, scope, promoted_from_hypothesis_id,
                    promoted_by_user_id, promotion_event_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(fake_vk_id),
                "legacy raw-stored row",
                _json.dumps(["LLM Cost"]),  # raw, non-canonical — pre-P2.1 style
                "{}",
                999,
                "[]",
                "personal",
                str(hyp.id),
                "legacy_user",
                str(fake_event_id),
            ),
        )
        conn.commit()

        # Both-sides normalization: "llm cost" query normalizes to "llm-cost";
        # stored "LLM Cost" also normalizes to "llm-cost" → match.
        results = lookup_verified_knowledge(["llm cost"], VKScope.PERSONAL, conn=conn)
        contents = {r.content for r in results}
        assert "legacy raw-stored row" in contents, (
            "legacy raw-stored row must be findable via both-sides normalization (no backfill)"
        )

    def test_d6_other_semantics_unchanged(self) -> None:
        """ADR-018 D7 AC#5: OR-semantics, ordering, empty-query ValueError unchanged."""
        store, conn = _make_full_store()
        with pytest.raises(ValueError):
            lookup_verified_knowledge([], VKScope.PERSONAL, conn=conn)
        _seed_and_promote(store, conn, content="t1", topic_tags=["tag-x"], last_validated_ts=2000)
        _seed_and_promote(store, conn, content="t2", topic_tags=["tag-y"], last_validated_ts=1000)
        results = lookup_verified_knowledge(["tag-x", "tag-y"], VKScope.PERSONAL, conn=conn)
        assert len(results) == 2
        assert results[0].last_validated == 2000  # DESC ordering preserved


# ---------------------------------------------------------------------------
# P2.5-2: list_room_topic_tags — deterministic canonical-tag union (ADR-021 D6)
# ---------------------------------------------------------------------------


def _seed_hypothesis_with_tags(
    store: EventStore,
    conn: sqlite3.Connection,
    room: Room,
    topic_tags: list[str],
) -> None:
    from orchestrator.core.event import Event, EventType, now_ms

    evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.UTTERANCE,
        author="user",
        timestamp=TimestampMs(now_ms()),
        content="msg",
    )
    store.append(evt)
    record_hypothesis(
        content="test hypothesis",
        room_id=room.id,
        source_event_ids=[evt.id],
        confidence=0.8,
        conn=conn,
        topic_tags=topic_tags,
    )


class TestListRoomTopicTags:
    def test_empty_room_returns_empty_list(self) -> None:
        """No hypotheses → list_room_topic_tags returns [].

        Discriminating: fails if the function returns all tags or raises on empty.
        """
        store, conn = _make_full_store()
        room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
        store.append_room(room)
        result = list_room_topic_tags(room.id, conn=conn)
        assert result == []

    def test_untagged_hypothesis_returns_empty(self) -> None:
        """Hypothesis with no topic_tags → [] returned."""
        store, conn = _make_full_store()
        room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
        store.append_room(room)
        _seed_hypothesis_with_tags(store, conn, room, [])
        result = list_room_topic_tags(room.id, conn=conn)
        assert result == []

    def test_single_hypothesis_tags_returned(self) -> None:
        """Single hypothesis with tags → those canonical tags returned."""
        store, conn = _make_full_store()
        room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
        store.append_room(room)
        _seed_hypothesis_with_tags(store, conn, room, ["LLM Cost", "ml-ops"])
        result = list_room_topic_tags(room.id, conn=conn)
        assert "llm-cost" in result
        assert "ml-ops" in result

    def test_multiple_hypotheses_union_deduplicated(self) -> None:
        """Two hypotheses with overlapping tags → union, no duplicates.

        Discriminating: if the function returned a list with duplicates,
        the dedup assertion would fail.
        """
        store, conn = _make_full_store()
        room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
        store.append_room(room)
        _seed_hypothesis_with_tags(store, conn, room, ["tag-alpha", "tag-shared"])
        _seed_hypothesis_with_tags(store, conn, room, ["tag-beta", "tag-shared"])
        result = list_room_topic_tags(room.id, conn=conn)
        assert result == sorted(set(result)), "result must be sorted and deduplicated"
        assert "tag-alpha" in result
        assert "tag-beta" in result
        assert "tag-shared" in result
        assert result.count("tag-shared") == 1, "duplicates must be removed"

    def test_returns_only_target_rooms_tags(self) -> None:
        """Tags from a different room are NOT included.

        Discriminating: fails if the function returns cross-room tags.
        """
        store, conn = _make_full_store()
        room1 = Room(id=generate_room_id(), type=RoomType.RESEARCH)
        room2 = Room(id=generate_room_id(), type=RoomType.RESEARCH)
        store.append_room(room1)
        store.append_room(room2)
        _seed_hypothesis_with_tags(store, conn, room1, ["room1-tag"])
        _seed_hypothesis_with_tags(store, conn, room2, ["room2-tag"])
        result1 = list_room_topic_tags(room1.id, conn=conn)
        assert "room1-tag" in result1
        assert "room2-tag" not in result1

    def test_result_is_sorted(self) -> None:
        """Result is sorted alphabetically — deterministic across calls."""
        store, conn = _make_full_store()
        room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
        store.append_room(room)
        _seed_hypothesis_with_tags(store, conn, room, ["zzz", "aaa", "mmm"])
        result = list_room_topic_tags(room.id, conn=conn)
        assert result == sorted(result)
