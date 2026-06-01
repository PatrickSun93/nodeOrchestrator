"""Tests for reentry/store.py — init_reentry_schema + reentry_marker round-trips.

Coverage standard:
  §6 schema — table creation is idempotent; round-trip insert/read.
  §1 N/A — store is a leaf module; cross-module integration in e2e test.
  §3 N/A — no subprocess/file handle outside context manager.
"""

from __future__ import annotations

import sqlite3

from orchestrator.core.event import RoomId, TimestampMs, generate_room_id
from orchestrator.core.event_store import EventStore
from orchestrator.memory.store import init_memory_schema
from orchestrator.reentry.store import get_leave_marker, init_reentry_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    init_reentry_schema(conn)
    return store, conn


def _seed_room(store: EventStore, conn: sqlite3.Connection) -> RoomId:
    from orchestrator.core.room import Room, RoomType

    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


# ---------------------------------------------------------------------------
# init_reentry_schema
# ---------------------------------------------------------------------------


def test_init_reentry_schema_creates_table() -> None:
    """init_reentry_schema creates reentry_marker table."""
    _, conn = _make_store()
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "reentry_marker" in tables


def test_init_reentry_schema_idempotent() -> None:
    """init_reentry_schema called twice does not raise."""
    _, conn = _make_store()
    init_reentry_schema(conn)  # second call
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "reentry_marker" in tables


# ---------------------------------------------------------------------------
# get_leave_marker
# ---------------------------------------------------------------------------


def test_get_leave_marker_absent_returns_none() -> None:
    """No marker present → get_leave_marker returns None."""
    _, conn = _make_store()
    result = get_leave_marker(RoomId("room_abc"), "user1", conn)
    assert result is None


def test_reentry_marker_round_trip_insert_read() -> None:
    """Direct insert round-trips through get_leave_marker (low-level storage test)."""
    _, conn = _make_store()
    room_id = RoomId("room_test")
    user_id = "user1"
    ts = 99000

    with conn:
        conn.execute(
            "INSERT INTO reentry_marker (room_id, user_id, last_seen_ts) VALUES (?, ?, ?)",
            (str(room_id), user_id, ts),
        )

    result = get_leave_marker(room_id, user_id, conn)
    assert result == TimestampMs(ts)


def test_reentry_marker_pk_one_row_per_room_user() -> None:
    """PK (room_id, user_id) — upsert updates in place; one row per pair."""
    _, conn = _make_store()
    room_id = RoomId("room_test")
    user_id = "user1"

    with conn:
        conn.execute(
            "INSERT INTO reentry_marker (room_id, user_id, last_seen_ts) VALUES (?, ?, ?)",
            (str(room_id), user_id, 1000),
        )
    # upsert
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO reentry_marker (room_id, user_id, last_seen_ts)
               VALUES (?, ?, ?)""",
            (str(room_id), user_id, 2000),
        )

    result = get_leave_marker(room_id, user_id, conn)
    assert result == TimestampMs(2000)
    row_count = conn.execute("SELECT COUNT(*) FROM reentry_marker").fetchone()[0]
    assert row_count == 1


def test_reentry_marker_distinct_users_distinct_rows() -> None:
    """Different user_ids for the same room are separate rows."""
    _, conn = _make_store()
    room_id = RoomId("room_multi")

    with conn:
        conn.execute("INSERT INTO reentry_marker VALUES (?, ?, ?)", (str(room_id), "alice", 100))
        conn.execute("INSERT INTO reentry_marker VALUES (?, ?, ?)", (str(room_id), "bob", 200))

    assert get_leave_marker(room_id, "alice", conn) == TimestampMs(100)
    assert get_leave_marker(room_id, "bob", conn) == TimestampMs(200)
