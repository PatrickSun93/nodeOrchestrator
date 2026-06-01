"""SQLite persistence for the reentry_marker table.

The leave-marker is consumer infrastructure — not a domain fact — so it lives
here (not in memory/). Co-located in the same SQLite file per ADR-016 D5's
same-file pattern. Per ADR-021 D5.
"""

from __future__ import annotations

import sqlite3

from orchestrator.core.event import RoomId, TimestampMs

_REENTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS reentry_marker (
    room_id   TEXT NOT NULL,
    user_id   TEXT NOT NULL,
    last_seen_ts INTEGER NOT NULL,
    PRIMARY KEY (room_id, user_id)
);
"""


def init_reentry_schema(conn: sqlite3.Connection) -> None:
    """Create the reentry_marker table. Idempotent (CREATE IF NOT EXISTS).

    Call after EventStore.init_schema + init_memory_schema on the same
    connection. Per ADR-021 D5.
    """
    conn.executescript(_REENTRY_SCHEMA)
    conn.commit()


def get_leave_marker(
    room_id: RoomId,
    user_id: str,
    conn: sqlite3.Connection,
) -> TimestampMs | None:
    """Return the last-seen timestamp for (room_id, user_id). None if absent."""
    row = conn.execute(
        "SELECT last_seen_ts FROM reentry_marker WHERE room_id = ? AND user_id = ?",
        (str(room_id), user_id),
    ).fetchone()
    if row is None:
        return None
    return TimestampMs(row[0])
