"""Event store: append-only persistence for events and rooms, plus a
relations cache for fast graph queries.

Three-layer append-only enforcement (see docs/architecture/event-model.md):
  1. Schema (TRIGGERs raise on UPDATE/DELETE).
  2. Application (Pydantic frozen=True on Event).
  3. Public API (no update/delete methods on EventStore).

The `relations` table is NOT append-only — it is a cache derived from
events by a pure function. It can be rebuilt at any time via
`recompute_relations()` or `recompute_all_relations()`, using the same
function as the write path.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from orchestrator.core.event import (
    Event,
    EventId,
    EventNotFoundError,
    EventType,
    InvalidParentError,
    Relation,
    RelationType,
    RoomId,
    RoomNotFoundError,
    TimestampMs,
    validate_metadata,
)
from orchestrator.core.relations import extract_structural_relations
from orchestrator.core.room import Room, RoomType

# ---------------------------------------------------------------------------
# Schema
#
# Tables and indices use IF NOT EXISTS — they hold data, so we never want
# to drop them on init. Triggers, by contrast, are pure logic — if a future
# version of the codebase changes the trigger body, IF NOT EXISTS would
# silently leave the OLD trigger installed (a recipe for hidden bugs).
# We use DROP + CREATE for triggers so init_schema() always installs the
# trigger code that's currently in this file.
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    room_id TEXT NOT NULL,
    type TEXT NOT NULL,
    author TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (parent_id) REFERENCES events(id),
    FOREIGN KEY (room_id) REFERENCES rooms(id)
);

-- Composite index covers `WHERE room_id = ? ORDER BY timestamp, id` queries
-- end-to-end (no separate sort step). The trailing `id` is the deterministic
-- tiebreaker for events at the same millisecond.
CREATE INDEX IF NOT EXISTS idx_events_room_ts_id
    ON events(room_id, timestamp, id);
CREATE INDEX IF NOT EXISTS idx_events_parent ON events(parent_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(room_id, type);

-- Triggers: DROP + CREATE so init_schema() always installs the latest body.
DROP TRIGGER IF EXISTS events_no_update;
CREATE TRIGGER events_no_update
BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

DROP TRIGGER IF EXISTS events_no_delete;
CREATE TRIGGER events_no_delete
BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TABLE IF NOT EXISTS relations (
    event_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_event_id TEXT NOT NULL,
    extracted_at INTEGER NOT NULL,
    PRIMARY KEY (event_id, relation_type, target_event_id),
    FOREIGN KEY (event_id) REFERENCES events(id),
    FOREIGN KEY (target_event_id) REFERENCES events(id)
);

CREATE INDEX IF NOT EXISTS idx_relations_target
    ON relations(target_event_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_relations_event
    ON relations(event_id);
"""


# ---------------------------------------------------------------------------
# Recursive CTE for thread reconstruction
#
# Walks parent_id upward in a single query. The path_seen column carries
# a delimited list of visited ids — the join condition rejects any
# parent that's already been seen, preventing infinite loops in the
# unlikely event of a cycle (defense in depth; the schema-level
# append-only triggers make parent_id cycles physically impossible).
#
# `depth` is bounded at 10000 as a hard ceiling — a 10000-deep thread
# would be pathological; this is a runaway guard, not an expected limit.
# ---------------------------------------------------------------------------

_THREAD_CTE = """
WITH RECURSIVE thread(
    id, parent_id, room_id, type, author, timestamp, content, metadata,
    depth, path_seen
) AS (
    SELECT id, parent_id, room_id, type, author, timestamp, content, metadata,
           0, '|' || id || '|'
      FROM events
     WHERE id = :event_id

    UNION ALL

    SELECT e.id, e.parent_id, e.room_id, e.type, e.author, e.timestamp,
           e.content, e.metadata,
           t.depth + 1,
           t.path_seen || e.id || '|'
      FROM events e
      JOIN thread t ON e.id = t.parent_id
     WHERE t.depth < 10000
       AND INSTR(t.path_seen, '|' || e.id || '|') = 0
)
SELECT id, parent_id, room_id, type, author, timestamp, content, metadata
  FROM thread
 ORDER BY depth DESC
"""


# ---------------------------------------------------------------------------
# EventStore
# ---------------------------------------------------------------------------


class EventStore:
    """Append-only event store backed by SQLite, plus a recomputable
    relations cache.

    Caller owns the sqlite3 connection's lifecycle. The store does not
    open or close the connection.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Wrap a sqlite3 connection.

        Note: this constructor does NOT enable foreign-key enforcement
        or run the schema. Call `init_schema()` to do both.
        """
        self.conn = conn
        # Ensure dict-style row access regardless of how the caller created
        # the connection.
        self.conn.row_factory = sqlite3.Row

    # -- schema ---------------------------------------------------------

    def init_schema(self) -> None:
        """Apply the schema (DDL + indices + TRIGGERs) and enable
        `PRAGMA foreign_keys = ON` on this connection.

        Idempotent: tables and indices use IF NOT EXISTS; triggers use
        DROP + CREATE (so calling on a pre-initialized DB always installs
        the trigger body that's currently in `SCHEMA`).
        """
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- writes ---------------------------------------------------------

    def append(self, event: Event) -> EventId:
        """Append an event to the log.

        Steps (metadata first; rest in a single transaction):
          0. Validate `event.metadata` via `validate_metadata`. Raises
             `MetadataValidationError` on schema violations for typed
             event types.
          1. (txn) Validate `event.room_id` exists. Raises
             `RoomNotFoundError`.
          2. (txn) If `event.parent_id` is not None, validate that:
             - it is not equal to `event.id`
               (else `InvalidParentError(reason="self_parent")`),
             - the parent event exists
               (else `InvalidParentError(reason="not_found")`),
             - the parent is in the same room as this event
               (else `InvalidParentError(reason="cross_room")`).
          3. (txn) INSERT the event row.
          4. (txn) Extract structural relations via
             `extract_structural_relations` and INSERT them.

        Returns:
            `event.id`.
        """
        # Step 0: pure validation, no txn needed.
        normalized_metadata = validate_metadata(event.type, event.metadata)

        with self.conn:
            # Step 1: room exists?
            row = self.conn.execute("SELECT 1 FROM rooms WHERE id = ?", (event.room_id,)).fetchone()
            if row is None:
                raise RoomNotFoundError(f"room {event.room_id!r} does not exist")

            # Step 2: parent valid?
            if event.parent_id is not None:
                if event.parent_id == event.id:
                    raise InvalidParentError(
                        "self_parent",
                        f"event {event.id!r} cannot be its own parent",
                    )
                parent_row = self.conn.execute(
                    "SELECT room_id FROM events WHERE id = ?",
                    (event.parent_id,),
                ).fetchone()
                if parent_row is None:
                    raise InvalidParentError(
                        "not_found",
                        f"parent event {event.parent_id!r} does not exist",
                    )
                if parent_row["room_id"] != event.room_id:
                    raise InvalidParentError(
                        "cross_room",
                        f"parent {event.parent_id!r} is in room "
                        f"{parent_row['room_id']!r}, not {event.room_id!r}",
                    )

            # Step 3: insert event row.
            self.conn.execute(
                """INSERT INTO events
                       (id, parent_id, room_id, type, author,
                        timestamp, content, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.id,
                    event.parent_id,
                    event.room_id,
                    event.type.value,
                    event.author,
                    event.timestamp,
                    event.content,
                    json.dumps(normalized_metadata),
                ),
            )

            # Step 4: extract and insert structural relations.
            event_normalized = event.model_copy(update={"metadata": normalized_metadata})
            relations = extract_structural_relations(event_normalized)
            if relations:
                self.conn.executemany(
                    """INSERT INTO relations
                           (event_id, relation_type, target_event_id, extracted_at)
                       VALUES (?, ?, ?, ?)""",
                    [
                        (r.event_id, r.relation_type.value, r.target_event_id, r.extracted_at)
                        for r in relations
                    ],
                )

        return event.id

    def append_room(self, room: Room) -> RoomId:
        """Insert a room. Returns the room id."""
        with self.conn:
            self.conn.execute(
                """INSERT INTO rooms (id, type, state, created_at)
                   VALUES (?, ?, ?, ?)""",
                (room.id, room.type.value, room.state, room.created_at),
            )
        return room.id

    # -- reads ----------------------------------------------------------

    def get_event(self, event_id: EventId) -> Event | None:
        """Fetch a single event by id. Returns None if not found.

        (Note: `get_thread` raises EventNotFoundError for unknown ids.
        The contract is intentionally different — see Principle 4 in
        event-model.md.)
        """
        row = self.conn.execute(
            """SELECT id, parent_id, room_id, type, author,
                      timestamp, content, metadata
               FROM events WHERE id = ?""",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_event(row)

    def get_thread(self, event_id: EventId) -> list[Event]:
        """Return the linear thread from the root to `event_id`, inclusive.

        Walks `parent_id` upward via a single recursive CTE (one query
        regardless of depth). Defends against `parent_id` cycles via a
        path-tracking column in the CTE: if a cycle is detected (which
        should be impossible at the schema level given append-only on
        `parent_id`, but guarded as a precaution), the recursion stops
        at the cycle entry and the partial path so far is returned.

        Raises:
            EventNotFoundError: `event_id` does not exist. Returning ``[]``
                would conflate "unknown id" with "empty thread" — but
                every event is at least the root of its own thread, so
                there is no empty case for a known id.

        Returns:
            List ordered from root to `event_id`.
        """
        rows = self.conn.execute(_THREAD_CTE, {"event_id": event_id}).fetchall()
        if not rows:
            raise EventNotFoundError(f"event {event_id!r} does not exist")
        return [self._row_to_event(row) for row in rows]

    def get_room_events(self, room_id: RoomId) -> list[Event]:
        """Return all events in a room.

        Ordered by `(timestamp ASC, id ASC)` — deterministic across
        events at the same millisecond. Index `idx_events_room_ts_id`
        covers this query end-to-end (no sort step).

        Returns ``[]`` if the room has no events OR if the room does
        not exist. The empty case is legitimate (a freshly created
        room is empty), so this method does NOT raise.
        """
        rows = self.conn.execute(
            """SELECT id, parent_id, room_id, type, author,
                      timestamp, content, metadata
               FROM events
               WHERE room_id = ?
               ORDER BY timestamp ASC, id ASC""",
            (room_id,),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_room(self, room_id: RoomId) -> Room | None:
        """Fetch a room by id. None if not found."""
        row = self.conn.execute(
            "SELECT id, type, state, created_at FROM rooms WHERE id = ?",
            (room_id,),
        ).fetchone()
        if row is None:
            return None
        return Room(
            id=RoomId(row["id"]),
            type=RoomType(row["type"]),
            state=row["state"],
            created_at=TimestampMs(row["created_at"]),
        )

    # -- relations cache ------------------------------------------------

    def get_relations_for(self, event_id: EventId) -> list[Relation]:
        """Outgoing relations from `event_id` (this event is the source).

        Ordered by relation_type for stable output across runs.
        """
        rows = self.conn.execute(
            """SELECT event_id, relation_type, target_event_id, extracted_at
               FROM relations
               WHERE event_id = ?
               ORDER BY relation_type, target_event_id""",
            (event_id,),
        ).fetchall()
        return [self._row_to_relation(row) for row in rows]

    def get_relations_to(
        self,
        target_event_id: EventId,
        relation_type: RelationType | None = None,
    ) -> list[Relation]:
        """Incoming relations pointing at `target_event_id`.

        Ordered by `extracted_at DESC`, so callers that want the latest
        edge (e.g. "latest event to retract X") can take ``[0]``.
        """
        if relation_type is None:
            rows = self.conn.execute(
                """SELECT event_id, relation_type, target_event_id, extracted_at
                   FROM relations
                   WHERE target_event_id = ?
                   ORDER BY extracted_at DESC""",
                (target_event_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT event_id, relation_type, target_event_id, extracted_at
                   FROM relations
                   WHERE target_event_id = ? AND relation_type = ?
                   ORDER BY extracted_at DESC""",
                (target_event_id, relation_type.value),
            ).fetchall()
        return [self._row_to_relation(row) for row in rows]

    def recompute_relations(self, event_id: EventId) -> int:
        """Recompute the relations cache for one event. Idempotent.

        Deletes existing relation rows where `relations.event_id ==
        event_id`, then re-extracts via `extract_structural_relations`
        and inserts. The events themselves are unchanged.

        Raises:
            EventNotFoundError: `event_id` does not exist.

        Returns:
            Number of relation edges in the cache for this event after
            recomputation.
        """
        event = self.get_event(event_id)
        if event is None:
            raise EventNotFoundError(f"event {event_id!r} does not exist")
        relations = extract_structural_relations(event)
        with self.conn:
            self.conn.execute("DELETE FROM relations WHERE event_id = ?", (event_id,))
            if relations:
                self.conn.executemany(
                    """INSERT INTO relations
                           (event_id, relation_type, target_event_id, extracted_at)
                       VALUES (?, ?, ?, ?)""",
                    [
                        (r.event_id, r.relation_type.value, r.target_event_id, r.extracted_at)
                        for r in relations
                    ],
                )
        return len(relations)

    def recompute_all_relations(self) -> int:
        """Drop and rebuild the entire relations cache from events.

        Useful when `extract_structural_relations` had a bug and the
        cache contains stale or wrong entries. The events table is
        untouched.

        Returns:
            Total number of relation edges in the cache after rebuild.
        """
        with self.conn:
            self.conn.execute("DELETE FROM relations")
            event_rows = self.conn.execute(
                """SELECT id, parent_id, room_id, type, author,
                          timestamp, content, metadata
                   FROM events
                   ORDER BY timestamp ASC, id ASC"""
            ).fetchall()
            all_relations: list[tuple[Any, ...]] = []
            for row in event_rows:
                event = self._row_to_event(row)
                for r in extract_structural_relations(event):
                    all_relations.append(
                        (r.event_id, r.relation_type.value, r.target_event_id, r.extracted_at)
                    )
            if all_relations:
                self.conn.executemany(
                    """INSERT INTO relations
                           (event_id, relation_type, target_event_id, extracted_at)
                       VALUES (?, ?, ?, ?)""",
                    all_relations,
                )
        return len(all_relations)

    # -- internal helpers -----------------------------------------------

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        return Event(
            id=EventId(row["id"]),
            parent_id=EventId(row["parent_id"]) if row["parent_id"] else None,
            room_id=RoomId(row["room_id"]),
            type=EventType(row["type"]),
            author=row["author"],
            timestamp=TimestampMs(row["timestamp"]),
            content=row["content"],
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _row_to_relation(row: sqlite3.Row) -> Relation:
        return Relation(
            event_id=EventId(row["event_id"]),
            relation_type=RelationType(row["relation_type"]),
            target_event_id=EventId(row["target_event_id"]),
            extracted_at=TimestampMs(row["extracted_at"]),
        )
