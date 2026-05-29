"""Tests for memory/store.py — schema init, record_hypothesis, row loaders.

Per plan P1.6.5-2 acceptance + docs/process/test-coverage-standard.md §5
(boundary validators multi-position).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.core.event import (
    EventId,
    RoomId,
    TimestampMs,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.exceptions import EventNotFoundError, MemoryStoreError
from orchestrator.memory.schema import HypothesisStatus, generate_hypothesis_id
from orchestrator.memory.store import (
    get_hypothesis_by_id,
    get_verified_knowledge_by_id,
    init_memory_schema,
    record_hypothesis,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _make_store_with_memory(
    conn: sqlite3.Connection | None = None,
) -> tuple[EventStore, sqlite3.Connection]:
    if conn is None:
        conn = _make_conn()
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return store, conn


def _seed_room_and_events(
    store: EventStore, conn: sqlite3.Connection, n_events: int = 2
) -> tuple[RoomId, list[EventId]]:
    from orchestrator.core.event import Event, EventType

    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    event_ids: list[EventId] = []
    for i in range(n_events):
        evt = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.UTTERANCE,
            author="user",
            timestamp=TimestampMs(now_ms() + i),
            content=f"message {i}",
        )
        store.append(evt)
        event_ids.append(evt.id)
    return room.id, event_ids


# ---------------------------------------------------------------------------
# init_memory_schema
# ---------------------------------------------------------------------------


class TestInitMemorySchema:
    def test_idempotent(self) -> None:
        conn = _make_conn()
        store = EventStore(conn)
        store.init_schema()
        init_memory_schema(conn)
        init_memory_schema(conn)  # second call must not raise

    def test_tables_exist_after_init(self) -> None:
        conn = _make_conn()
        store = EventStore(conn)
        store.init_schema()
        init_memory_schema(conn)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "hypothesis" in tables
        assert "verified_knowledge" in tables
        assert "entity" in tables

    def test_insert_time_fk_enforcement(self) -> None:
        """FK enforcement is INSERT-time, not CREATE-time (ADR-016 D5).

        init_memory_schema against a bare connection (without EventStore.init_schema)
        succeeds at CREATE, but the first INSERT into hypothesis (which FKs rooms)
        raises because the rooms table doesn't exist.
        """
        conn = _make_conn()
        conn.execute("PRAGMA foreign_keys = ON")
        # NOTE: EventStore.init_schema NOT called — rooms/events tables absent.
        init_memory_schema(conn)  # CREATE succeeds (forward FK ref is allowed)
        # INSERT should raise because rooms table doesn't exist
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO hypothesis"
                " (id, content, room_id, confidence, source_event_ids, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("hyp_x", "content", "room_x", 0.5, '["evt_x"]', 1700000000000),
            )

    def test_on_disk_migration(self, tmp_path: Path) -> None:
        """On-disk migration: existing DB gets memory tables added without data loss.

        Per ADR-016 D5 on-disk migration claim (external Y11 → alpha): init
        event_store on a disk-backed DB, append rooms + events, close + reopen,
        run init_memory_schema, assert memory tables exist AND event/room counts
        preserved, assert record_hypothesis works post-migration.
        """
        db_path = tmp_path / "test.db"

        # Phase 1: init event store and append data.
        conn1 = sqlite3.connect(str(db_path))
        conn1.row_factory = sqlite3.Row
        store1 = EventStore(conn1)
        store1.init_schema()
        room_id, event_ids = _seed_room_and_events(store1, conn1, n_events=3)
        conn1.close()

        # Phase 2: reopen and run init_memory_schema (simulates migration).
        conn2 = sqlite3.connect(str(db_path))
        conn2.row_factory = sqlite3.Row
        conn2.execute("PRAGMA foreign_keys = ON")
        init_memory_schema(conn2)

        # Memory tables exist.
        tables = {
            row[0]
            for row in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "hypothesis" in tables
        assert "verified_knowledge" in tables

        # Existing event/room data preserved.
        room_count = conn2.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
        event_count = conn2.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert room_count == 1
        assert event_count == 3

        # record_hypothesis works against migrated DB.
        hyp = record_hypothesis(
            content="post-migration hypothesis",
            room_id=room_id,
            source_event_ids=event_ids[:2],
            confidence=0.6,
            conn=conn2,
        )
        assert hyp.content == "post-migration hypothesis"
        conn2.close()


# ---------------------------------------------------------------------------
# record_hypothesis
# ---------------------------------------------------------------------------


class TestRecordHypothesis:
    def test_happy_path_returns_hypothesis(self) -> None:
        store, conn = _make_store_with_memory()
        room_id, event_ids = _seed_room_and_events(store, conn)
        hyp = record_hypothesis(
            content="The sky is blue.",
            room_id=room_id,
            source_event_ids=event_ids,
            confidence=0.8,
            conn=conn,
        )
        assert hyp.content == "The sky is blue."
        assert hyp.status == HypothesisStatus.PENDING
        assert hyp.candidate_for_promotion is False
        assert hyp.room_id == room_id
        assert hyp.confidence == 0.8
        assert list(hyp.source_event_ids) == event_ids

    def test_row_persisted(self) -> None:
        store, conn = _make_store_with_memory()
        room_id, event_ids = _seed_room_and_events(store, conn)
        hyp = record_hypothesis(
            content="persisted claim",
            room_id=room_id,
            source_event_ids=event_ids,
            confidence=0.5,
            conn=conn,
        )
        loaded = get_hypothesis_by_id(hyp.id, conn=conn)
        assert loaded is not None
        assert loaded.id == hyp.id
        assert loaded.content == "persisted claim"

    def test_id_has_hyp_prefix(self) -> None:
        store, conn = _make_store_with_memory()
        room_id, event_ids = _seed_room_and_events(store, conn)
        hyp = record_hypothesis(
            content="x", room_id=room_id, source_event_ids=event_ids, confidence=0.5, conn=conn
        )
        assert hyp.id.startswith("hyp_")

    def test_source_event_ids_empty_rejected(self) -> None:
        store, conn = _make_store_with_memory()
        room_id, _ = _seed_room_and_events(store, conn, n_events=0)
        with pytest.raises(ValidationError):
            record_hypothesis(
                content="bad", room_id=room_id, source_event_ids=[], confidence=0.5, conn=conn
            )

    def test_confidence_out_of_range(self) -> None:
        store, conn = _make_store_with_memory()
        room_id, event_ids = _seed_room_and_events(store, conn)
        with pytest.raises(ValidationError):
            record_hypothesis(
                content="x", room_id=room_id, source_event_ids=event_ids, confidence=1.5, conn=conn
            )
        with pytest.raises(ValidationError):
            record_hypothesis(
                content="x", room_id=room_id, source_event_ids=event_ids, confidence=-0.1, conn=conn
            )

    def test_confidence_boundary_0_and_1(self) -> None:
        store, conn = _make_store_with_memory()
        room_id, event_ids = _seed_room_and_events(store, conn)
        h0 = record_hypothesis(
            content="low", room_id=room_id, source_event_ids=event_ids, confidence=0.0, conn=conn
        )
        assert h0.confidence == 0.0
        h1 = record_hypothesis(
            content="high", room_id=room_id, source_event_ids=event_ids, confidence=1.0, conn=conn
        )
        assert h1.confidence == 1.0

    def test_empty_content_rejected(self) -> None:
        store, conn = _make_store_with_memory()
        room_id, event_ids = _seed_room_and_events(store, conn)
        with pytest.raises(ValidationError):
            record_hypothesis(
                content="", room_id=room_id, source_event_ids=event_ids, confidence=0.5, conn=conn
            )

    def test_source_event_id_existence_check_missing_raises(self) -> None:
        """Per ADR-016 D2 producer-time existence check (Y2 alpha-(ii)):
        any missing source_event_id raises EventNotFoundError + no row inserted."""
        store, conn = _make_store_with_memory()
        room_id, event_ids = _seed_room_and_events(store, conn)
        fake_id = EventId("evt_" + "0" * 32)
        with pytest.raises(EventNotFoundError) as exc_info:
            record_hypothesis(
                content="x",
                room_id=room_id,
                source_event_ids=[event_ids[0], fake_id],
                confidence=0.5,
                conn=conn,
            )
        assert exc_info.value.event_id == fake_id
        # No row inserted.
        count = conn.execute("SELECT COUNT(*) FROM hypothesis").fetchone()[0]
        assert count == 0

    def test_source_event_ids_all_exist_no_error(self) -> None:
        store, conn = _make_store_with_memory()
        room_id, event_ids = _seed_room_and_events(store, conn, n_events=4)
        hyp = record_hypothesis(
            content="all present",
            room_id=room_id,
            source_event_ids=event_ids,
            confidence=0.7,
            conn=conn,
        )
        assert hyp is not None

    def test_room_id_fk_enforcement(self) -> None:
        """room_id not in rooms table raises (FK enforcement)."""
        store, conn = _make_store_with_memory()
        _room_id, event_ids = _seed_room_and_events(store, conn)
        bad_room = RoomId("room_" + "x" * 32)
        with pytest.raises(Exception) as exc_info:
            record_hypothesis(
                content="x",
                room_id=bad_room,
                source_event_ids=event_ids,
                confidence=0.5,
                conn=conn,
            )
        # FK violation is wrapped as MemoryStoreError or propagates as IntegrityError.
        assert isinstance(exc_info.value, (MemoryStoreError, sqlite3.IntegrityError))

    def test_source_event_ids_batch_check_3plus(self) -> None:
        """With 3+ source_event_ids, the batch SELECT path is used."""
        store, conn = _make_store_with_memory()
        room_id, event_ids = _seed_room_and_events(store, conn, n_events=4)
        hyp = record_hypothesis(
            content="batch check",
            room_id=room_id,
            source_event_ids=event_ids,
            confidence=0.6,
            conn=conn,
        )
        assert len(hyp.source_event_ids) == 4


# ---------------------------------------------------------------------------
# get_hypothesis_by_id / get_verified_knowledge_by_id
# ---------------------------------------------------------------------------


class TestGetters:
    def test_get_hypothesis_absent_returns_none(self) -> None:
        _store, conn = _make_store_with_memory()
        assert get_hypothesis_by_id(generate_hypothesis_id(), conn=conn) is None

    def test_get_vk_absent_returns_none(self) -> None:
        from orchestrator.memory.schema import generate_vk_id

        _store, conn = _make_store_with_memory()
        assert get_verified_knowledge_by_id(generate_vk_id(), conn=conn) is None

    def test_round_trip_hypothesis(self) -> None:
        store, conn = _make_store_with_memory()
        room_id, event_ids = _seed_room_and_events(store, conn)
        hyp = record_hypothesis(
            content="round trip",
            room_id=room_id,
            source_event_ids=event_ids,
            confidence=0.75,
            conn=conn,
        )
        loaded = get_hypothesis_by_id(hyp.id, conn=conn)
        assert loaded is not None
        assert loaded == hyp
