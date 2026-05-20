"""Shared fixtures for tests/autonomy/.

``event_store`` — a fresh in-memory EventStore with schema initialized.
``room_id``     — a room pre-created in that store.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from orchestrator.core.event import RoomId, TimestampMs, generate_room_id, now_ms
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def event_store(conn: sqlite3.Connection) -> EventStore:
    store = EventStore(conn)
    store.init_schema()
    return store


@pytest.fixture
def room_id(event_store: EventStore) -> RoomId:
    rid = generate_room_id()
    event_store.append_room(Room(id=rid, type=RoomType.RESEARCH, created_at=TimestampMs(now_ms())))
    return rid
