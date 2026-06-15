"""EventStore behavior tests: append, reads, parent validation, schema."""

from __future__ import annotations

import sqlite3
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import pytest

from orchestrator.core.event import (
    Event,
    EventId,
    EventNotFoundError,
    EventType,
    InvalidParentError,
    MetadataValidationError,
    RoomId,
    RoomNotFoundError,
    TimestampMs,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType

if TYPE_CHECKING:
    from .conftest import PopulatedFixture


def _make_event(
    room_id: RoomId,
    *,
    event_type: EventType = EventType.UTTERANCE,
    parent_id: EventId | None = None,
    author: str = "user",
    content: str = "hi",
    metadata: dict[str, Any] | None = None,
    timestamp: TimestampMs | None = None,
    event_id: EventId | None = None,
) -> Event:
    return Event(
        id=event_id if event_id is not None else generate_event_id(),
        parent_id=parent_id,
        room_id=room_id,
        type=event_type,
        author=author,
        timestamp=timestamp if timestamp is not None else now_ms(),
        content=content,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# init_schema
# ---------------------------------------------------------------------------


class TestInitSchema:
    def test_init_schema_idempotent(self, conn: sqlite3.Connection) -> None:
        """Calling init_schema twice must not raise; tables IF NOT EXISTS,
        triggers DROP+CREATE."""
        store = EventStore(conn)
        store.init_schema()
        store.init_schema()

        # Store still works after re-init.
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        assert store.get_room(room.id) is not None

    def test_foreign_keys_enabled_after_init(self, conn: sqlite3.Connection) -> None:
        store = EventStore(conn)
        store.init_schema()
        cursor = conn.execute("PRAGMA foreign_keys")
        row = cursor.fetchone()
        assert row[0] == 1


# ---------------------------------------------------------------------------
# append (basic round-trip)
# ---------------------------------------------------------------------------


class TestAppendBasic:
    def test_append_returns_event_id(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        e = _make_event(room.id, event_type=EventType.USER_INPUT)
        assert store.append(e) == e.id

    def test_get_event_after_append(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        e = _make_event(room.id, content="hello world")
        store.append(e)
        fetched = store.get_event(e.id)
        assert fetched is not None
        assert fetched.id == e.id
        assert fetched.content == "hello world"
        assert fetched.author == "user"
        assert fetched.metadata == {}

    def test_get_event_unknown_returns_none(self, in_memory_event_store: EventStore) -> None:
        assert in_memory_event_store.get_event(EventId("evt_missing")) is None

    def test_metadata_normalized_at_append(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        e = _make_event(
            room.id,
            event_type=EventType.HYPOTHESIS,
            author="agent:operator",
            metadata={"confidence": 0.5},
        )
        store.append(e)
        fetched = store.get_event(e.id)
        assert fetched is not None
        # `based_on` default appears in the stored form.
        assert fetched.metadata == {"confidence": 0.5, "based_on": []}


# ---------------------------------------------------------------------------
# Room/parent validation at write time
# ---------------------------------------------------------------------------


class TestRoomNotFound:
    def test_unknown_room_raises(self, in_memory_event_store: EventStore) -> None:
        e = _make_event(RoomId("room_doesnt_exist"))
        with pytest.raises(RoomNotFoundError):
            in_memory_event_store.append(e)


class TestParentValidation:
    """append() validates parent_id at write time; three failure modes,
    one exception class, three reason values."""

    def test_parent_not_found(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        e = _make_event(room.id, parent_id=EventId("evt_nonexistent"))
        with pytest.raises(InvalidParentError) as exc:
            store.append(e)
        assert exc.value.reason == "not_found"

    def test_self_parent(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        eid = generate_event_id()
        e = Event(
            id=eid,
            parent_id=eid,
            room_id=room.id,
            type=EventType.UTTERANCE,
            author="user",
            timestamp=now_ms(),
            content="self",
        )
        with pytest.raises(InvalidParentError) as exc:
            store.append(e)
        assert exc.value.reason == "self_parent"

    def test_cross_room_parent(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room_a = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        room_b = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room_a)
        store.append_room(room_b)
        e_a = _make_event(room_a.id, event_type=EventType.USER_INPUT)
        store.append(e_a)
        e_b = _make_event(room_b.id, parent_id=e_a.id)
        with pytest.raises(InvalidParentError) as exc:
            store.append(e_b)
        assert exc.value.reason == "cross_room"

    def test_reason_supports_match(self, in_memory_event_store: EventStore) -> None:
        """The Literal reason supports `match` discrimination — Mypy
        can flag missing cases. Run-time test confirms the field is set."""
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        e = _make_event(room.id, parent_id=EventId("evt_nonexistent"))
        try:
            store.append(e)
        except InvalidParentError as exc:
            tag: str
            match exc.reason:
                case "not_found":
                    tag = "not_found"
                case "cross_room":
                    tag = "cross_room"
                case "self_parent":
                    tag = "self_parent"
            assert tag == "not_found"
        else:
            pytest.fail("append should have raised InvalidParentError")


class TestMetadataValidationAtAppend:
    def test_invalid_metadata_for_typed_type(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        e = _make_event(
            room.id,
            event_type=EventType.HYPOTHESIS,
            author="agent:operator",
            metadata={"confidence": 5.0},
        )
        with pytest.raises(MetadataValidationError):
            store.append(e)

    def test_open_metadata_passes_through(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        e = _make_event(
            room.id,
            event_type=EventType.UTTERANCE,
            metadata={"anything": "goes"},
        )
        store.append(e)
        fetched = store.get_event(e.id)
        assert fetched is not None
        assert fetched.metadata == {"anything": "goes"}


# ---------------------------------------------------------------------------
# Reads: get_thread, get_room_events
# ---------------------------------------------------------------------------


class TestThreadReads:
    def test_thread_linear_root_first(self, populated_event_store: PopulatedFixture) -> None:
        store, ids = populated_event_store
        # rejection thread (depth 7):
        # user_input → utterance → tool_call → tool_result
        #   → hypothesis → decision → rejection
        thread = store.get_thread(ids["rejection"])
        assert len(thread) == 7
        assert thread[0].id == ids["user_input"]
        assert thread[-1].id == ids["rejection"]
        # Adjacency: each event's parent is the previous element.
        for prev, curr in pairwise(thread):
            assert curr.parent_id == prev.id

    def test_thread_root_event_singleton(self, populated_event_store: PopulatedFixture) -> None:
        store, ids = populated_event_store
        thread = store.get_thread(ids["user_input"])
        assert len(thread) == 1
        assert thread[0].id == ids["user_input"]
        assert thread[0].parent_id is None

    def test_thread_unknown_raises(self, in_memory_event_store: EventStore) -> None:
        with pytest.raises(EventNotFoundError):
            in_memory_event_store.get_thread(EventId("evt_does_not_exist"))

    def test_retraction_thread_includes_decision(
        self, populated_event_store: PopulatedFixture
    ) -> None:
        """Retraction is a child of decision (not sibling), so the thread
        from retraction includes the decision being retracted. This is
        why retraction-as-child semantically holds: thread reconstruction
        must surface the event being retracted."""
        store, ids = populated_event_store
        thread = store.get_thread(ids["retraction"])
        thread_ids = [e.id for e in thread]
        assert ids["decision"] in thread_ids


class TestRoomEvents:
    def test_room_events_in_order(self, populated_event_store: PopulatedFixture) -> None:
        store, ids = populated_event_store
        events = store.get_room_events(ids["room"])
        assert len(events) == 8
        # Ordered by (timestamp ASC, id ASC).
        for prev, curr in pairwise(events):
            assert (prev.timestamp, prev.id) <= (curr.timestamp, curr.id)

    def test_room_events_unknown_room_returns_empty(
        self, in_memory_event_store: EventStore
    ) -> None:
        """Unlike get_thread, this returns []. A freshly created room
        is empty — the empty case is legitimate, not a bug signal."""
        assert in_memory_event_store.get_room_events(RoomId("room_x")) == []

    def test_room_events_empty_room_returns_empty(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        assert store.get_room_events(room.id) == []


# ---------------------------------------------------------------------------
# Room storage
# ---------------------------------------------------------------------------


class TestRoomStorage:
    def test_get_room(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        room = Room(
            id=generate_room_id(),
            type=RoomType.RESEARCH,
            state="open",
        )
        store.append_room(room)
        fetched = store.get_room(room.id)
        assert fetched is not None
        assert fetched.id == room.id
        assert fetched.type == RoomType.RESEARCH

    def test_get_room_unknown_returns_none(self, in_memory_event_store: EventStore) -> None:
        assert in_memory_event_store.get_room(RoomId("room_x")) is None

    def test_list_room_ids_empty(self, in_memory_event_store: EventStore) -> None:
        assert in_memory_event_store.list_room_ids() == []

    def test_list_room_ids_populated(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        r1 = Room(id=generate_room_id(), type=RoomType.RESEARCH, state="open")
        r2 = Room(id=generate_room_id(), type=RoomType.FREE_CHAT, state="open")
        store.append_room(r1)
        store.append_room(r2)
        ids = store.list_room_ids()
        assert len(ids) == 2
        assert r1.id in ids
        assert r2.id in ids

    def test_list_room_ids_read_only(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        store.append_room(Room(id=generate_room_id(), type=RoomType.RESEARCH, state="open"))
        ids = store.list_room_ids()
        assert len(ids) == 1
        # list_room_ids is a reader — modifying the returned list does not affect the store
        ids.clear()
        assert len(store.list_room_ids()) == 1

    def test_list_rooms_empty(self, in_memory_event_store: EventStore) -> None:
        assert in_memory_event_store.list_rooms() == []

    def test_list_rooms_all_returned(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        r1 = Room(id=generate_room_id(), type=RoomType.RESEARCH, state="open")
        r2 = Room(id=generate_room_id(), type=RoomType.FREE_CHAT, state="open")
        store.append_room(r1)
        store.append_room(r2)
        rooms = store.list_rooms()
        assert len(rooms) == 2
        ids = [room.id for room in rooms]
        assert r1.id in ids
        assert r2.id in ids

    def test_list_rooms_ordered_created_at_asc(self, in_memory_event_store: EventStore) -> None:
        store = in_memory_event_store
        r1 = Room(id=generate_room_id(), type=RoomType.RESEARCH, state="open")
        r2 = Room(id=generate_room_id(), type=RoomType.FREE_CHAT, state="open")
        r3 = Room(id=generate_room_id(), type=RoomType.BUG_FIX, state="open")
        store.append_room(r1)
        store.append_room(r2)
        store.append_room(r3)
        rooms = store.list_rooms()
        assert len(rooms) == 3
        assert rooms[0].id == r1.id
        assert rooms[1].id == r2.id
        assert rooms[2].id == r3.id


# ---------------------------------------------------------------------------
# append_in_transaction (ADR-016 D11 / P1.6.5-2)
# ---------------------------------------------------------------------------


class TestAppendInTransaction:
    def test_bare_call_raises_runtime_error(self, in_memory_event_store: EventStore) -> None:
        """Calling append_in_transaction outside an active transaction raises RuntimeError.

        This guards the silent-data-loss path: a bare call would start an
        implicit transaction that is never committed (proxy Y2 alpha-(b)).
        """
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        event = _make_event(room.id)
        with pytest.raises(RuntimeError, match="append_in_transaction"):
            store.append_in_transaction(event)

    def test_call_inside_managed_txn_succeeds(self, in_memory_event_store: EventStore) -> None:
        """Call inside a with-conn block (after prior DML) succeeds.

        The caller must execute at least one DML statement before calling
        append_in_transaction (Python sqlite3 only sets in_transaction=True
        after first DML). Here we insert a room row as the prior DML.
        """
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        room2 = Room(id=generate_room_id(), type=RoomType.RESEARCH)
        store.append_room(room)  # seed rooms table
        actual_event = _make_event(room.id)

        with store.conn:
            # Prior DML: insert another room to start the transaction.
            store.conn.execute(
                "INSERT INTO rooms (id, type, state, created_at) VALUES (?, ?, ?, ?)",
                (str(room2.id), room2.type.value, room2.state, room2.created_at),
            )
            # Now in_transaction=True.
            returned_id = store.append_in_transaction(actual_event)

        assert returned_id == actual_event.id
        assert store.get_event(actual_event.id) is not None
        # Both rooms committed atomically.
        assert store.get_room(room2.id) is not None

    def test_rollback_on_exception(self, in_memory_event_store: EventStore) -> None:
        """Exception inside with-conn rolls back the appended event.

        The event must NOT appear in the store after rollback.
        """
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        event = _make_event(room.id)

        with pytest.raises(ValueError), store.conn:
            store.conn.execute(
                "INSERT INTO rooms (id, type, state, created_at) VALUES (?, ?, ?, ?)",
                (str(generate_room_id()), room.type.value, "open", now_ms()),
            )
            store.append_in_transaction(event)
            raise ValueError("deliberate failure")

        # Event must NOT be in the store (rolled back).
        assert store.get_event(event.id) is None

    def test_append_wrapper_behavior_preserved(self, in_memory_event_store: EventStore) -> None:
        """The public append() method still works correctly after the split.

        The split must be behavior-preserving for all 6 existing callers.
        This test verifies the basic happy path is unchanged.
        """
        store = in_memory_event_store
        room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
        store.append_room(room)
        event = _make_event(room.id)
        returned_id = store.append(event)
        assert returned_id == event.id
        assert store.get_event(event.id) is not None

    def test_append_unknown_room_still_raises(self, in_memory_event_store: EventStore) -> None:
        """append() RoomNotFoundError still works after the split."""
        store = in_memory_event_store
        event = _make_event(RoomId("room_" + "0" * 32))
        with pytest.raises(RoomNotFoundError):
            store.append(event)
