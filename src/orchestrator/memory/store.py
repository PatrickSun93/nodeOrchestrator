"""SQLite persistence for memory tables (Hypothesis + VerifiedKnowledge + Entity).

Per ADR-016 D5: memory tables co-locate with the event_store SQLite file.
Same connection enables single-transaction atomicity (D11).

Schema init: call init_memory_schema(conn) AFTER EventStore.init_schema(conn)
on the same connection. FK enforcement is at INSERT time (not CREATE time),
so init order matters for INSERT correctness, not for CREATE success.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from orchestrator.core.event import EventId, RoomId, TimestampMs, now_ms
from orchestrator.memory.exceptions import EventNotFoundError, MemoryStoreError
from orchestrator.memory.schema import (
    Hypothesis,
    HypothesisId,
    HypothesisStatus,
    VerifiedKnowledge,
    VKId,
    generate_hypothesis_id,
)

# ---------------------------------------------------------------------------
# Memory schema DDL
# ---------------------------------------------------------------------------

_MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS hypothesis (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    room_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_event_ids TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    candidate_for_promotion INTEGER NOT NULL DEFAULT 0,
    topic_tags TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL,
    FOREIGN KEY (room_id) REFERENCES rooms(id)
);
CREATE INDEX IF NOT EXISTS idx_hypothesis_room
    ON hypothesis(room_id);
CREATE INDEX IF NOT EXISTS idx_hypothesis_status_candidate
    ON hypothesis(status, candidate_for_promotion);

CREATE TABLE IF NOT EXISTS verified_knowledge (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    topic_tags TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '{}',
    last_validated INTEGER NOT NULL,
    contradictions TEXT NOT NULL DEFAULT '[]',
    scope TEXT NOT NULL,
    promoted_from_hypothesis_id TEXT NOT NULL UNIQUE,
    promoted_by_user_id TEXT NOT NULL,
    promotion_event_id TEXT NOT NULL,
    FOREIGN KEY (promoted_from_hypothesis_id) REFERENCES hypothesis(id),
    FOREIGN KEY (promotion_event_id) REFERENCES events(id)
);
CREATE INDEX IF NOT EXISTS idx_vk_scope_last_validated
    ON verified_knowledge(scope, last_validated DESC);

CREATE TABLE IF NOT EXISTS entity (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    attributes TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tag (
    canonical TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------


def _ensure_hypothesis_topic_tags(conn: sqlite3.Connection) -> None:
    """Idempotent ALTER-TABLE guard for the topic_tags column (ADR-018 D5).

    Called after executescript(_MEMORY_SCHEMA) in init_memory_schema.
    Fresh DBs already have the column via CREATE TABLE; pre-P2.1 DBs need
    the ALTER. SQLite backfills the DEFAULT '[]' constant into existing rows.
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(hypothesis)")}
    if "topic_tags" not in cols:
        conn.execute(
            "ALTER TABLE hypothesis ADD COLUMN topic_tags TEXT NOT NULL DEFAULT '[]'"
        )


def init_memory_schema(conn: sqlite3.Connection) -> None:
    """Create hypothesis + verified_knowledge + entity + tag tables + indexes.

    Idempotent (CREATE TABLE IF NOT EXISTS + ALTER TABLE guard). Per ADR-016
    D5 + ADR-018 D5: call AFTER EventStore.init_schema(conn). FK enforcement
    is INSERT-time, so CREATE succeeds even if events/rooms tables don't exist
    yet; the first INSERT into a FK-referencing column against a missing table
    raises "no such table".
    """
    conn.executescript(_MEMORY_SCHEMA)
    _ensure_hypothesis_topic_tags(conn)
    conn.commit()


# ---------------------------------------------------------------------------
# Hypothesis producer
# ---------------------------------------------------------------------------


def record_hypothesis(
    content: str,
    room_id: RoomId,
    source_event_ids: list[EventId],
    confidence: float,
    *,
    conn: sqlite3.Connection,
    now: TimestampMs | None = None,
) -> Hypothesis:
    """Insert a new Hypothesis row. Pure producer — does NOT touch event_store.

    Caller chooses whether to also emit a `hypothesis` event into the
    event stream (if at all). Memory table and event stream are NOT
    auto-synced. Per ADR-016 D4.

    Raises:
        pydantic.ValidationError: if any field fails schema validation
            (e.g., confidence out of [0.0, 1.0], source_event_ids empty,
            content empty, room_id FK failure).
        EventNotFoundError: if any source_event_id is absent from the
            event store (per ADR-016 D2 producer-time existence check,
            Y2 alpha-(ii) routing).
        MemoryStoreError: on unexpected SQLite failure.
    """
    ts = now if now is not None else now_ms()
    hyp = Hypothesis(
        id=generate_hypothesis_id(),
        content=content,
        room_id=room_id,
        confidence=confidence,
        source_event_ids=source_event_ids,
        created_at=ts,
    )

    # Producer-time existence check: raise EventNotFoundError if any
    # source_event_id is missing. Per ADR-016 D2 integrity guarantee.
    if len(source_event_ids) >= 3:
        placeholders = ",".join("?" * len(source_event_ids))
        rows = conn.execute(
            f"SELECT id FROM events WHERE id IN ({placeholders})",
            tuple(source_event_ids),
        ).fetchall()
        found = {row["id"] for row in rows}
        for eid in source_event_ids:
            if eid not in found:
                raise EventNotFoundError(eid)
    else:
        for eid in source_event_ids:
            row = conn.execute("SELECT 1 FROM events WHERE id = ?", (eid,)).fetchone()
            if row is None:
                raise EventNotFoundError(eid)

    try:
        with conn:
            conn.execute(
                """INSERT INTO hypothesis
                       (id, content, room_id, confidence, source_event_ids,
                        status, candidate_for_promotion, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    hyp.id,
                    hyp.content,
                    str(hyp.room_id),
                    hyp.confidence,
                    json.dumps(list(hyp.source_event_ids)),
                    hyp.status.value,
                    int(hyp.candidate_for_promotion),
                    hyp.created_at,
                ),
            )
    except sqlite3.Error as exc:
        raise MemoryStoreError(f"failed to insert hypothesis: {exc}") from exc

    return hyp


# ---------------------------------------------------------------------------
# Row loaders
# ---------------------------------------------------------------------------


def get_hypothesis_by_id(
    hyp_id: HypothesisId,
    *,
    conn: sqlite3.Connection,
) -> Hypothesis | None:
    """Load a Hypothesis by id. Returns None if absent."""
    row = conn.execute("SELECT * FROM hypothesis WHERE id = ?", (hyp_id,)).fetchone()
    if row is None:
        return None
    return _row_to_hypothesis(row)


def get_verified_knowledge_by_id(
    vk_id: VKId,
    *,
    conn: sqlite3.Connection,
) -> VerifiedKnowledge | None:
    """Load a VerifiedKnowledge by id. Returns None if absent."""
    row = conn.execute("SELECT * FROM verified_knowledge WHERE id = ?", (vk_id,)).fetchone()
    if row is None:
        return None
    return _row_to_vk(row)


# ---------------------------------------------------------------------------
# Internal row helpers
# ---------------------------------------------------------------------------


def _row_to_hypothesis(row: sqlite3.Row) -> Hypothesis:
    return Hypothesis(
        id=HypothesisId(row["id"]),
        content=row["content"],
        room_id=RoomId(row["room_id"]),
        confidence=row["confidence"],
        source_event_ids=[EventId(e) for e in json.loads(row["source_event_ids"])],
        status=HypothesisStatus(row["status"]),
        candidate_for_promotion=bool(row["candidate_for_promotion"]),
        topic_tags=json.loads(row["topic_tags"]),
        created_at=TimestampMs(row["created_at"]),
    )


def _row_to_vk(row: sqlite3.Row) -> VerifiedKnowledge:
    from orchestrator.memory.schema import EntityType, VKScope  # noqa: F401 (used via dict)

    raw: dict[str, Any] = dict(row)
    return VerifiedKnowledge(
        id=VKId(raw["id"]),
        content=raw["content"],
        topic_tags=json.loads(raw["topic_tags"]),
        evidence=json.loads(raw["evidence"]),
        last_validated=TimestampMs(raw["last_validated"]),
        contradictions=[VKId(v) for v in json.loads(raw["contradictions"])],
        scope=raw["scope"],
        promoted_from_hypothesis_id=HypothesisId(raw["promoted_from_hypothesis_id"]),
        promoted_by_user_id=raw["promoted_by_user_id"],
        promotion_event_id=EventId(raw["promotion_event_id"]),
    )
