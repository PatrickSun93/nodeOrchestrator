"""Tests for memory/lookup.py — lookup_verified_knowledge.

Per plan P1.6.5-4 acceptance:
  - scope filter, topic_tags OR-semantics, empty topic_tags ValueError,
    ordering last_validated DESC + tie-break id ASC, cross-room inclusion,
    no LLM call (constitutional test stays green).
"""

from __future__ import annotations

import sqlite3

import pytest

from orchestrator.core.event import TimestampMs, generate_event_id, generate_room_id
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.lookup import lookup_verified_knowledge
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
