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
    Entity,
    EntityId,
    EntityScope,
    EntityType,
    Hypothesis,
    HypothesisId,
    HypothesisStatus,
    ProjectArchive,
    VerifiedKnowledge,
    VKId,
    generate_hypothesis_id,
)
from orchestrator.memory.tags import resolve_tags

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
    scope TEXT NOT NULL DEFAULT 'personal',
    evidence TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS project_archive (
    room_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    one_line_summary TEXT NOT NULL,
    decision_log TEXT NOT NULL DEFAULT '[]',
    spinoff_questions TEXT NOT NULL DEFAULT '[]',
    scope TEXT NOT NULL DEFAULT 'project',
    evidence TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    FOREIGN KEY (room_id) REFERENCES rooms(id)
);

CREATE TABLE IF NOT EXISTS tag (
    canonical TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------


def _ensure_entity_columns(conn: sqlite3.Connection) -> None:
    """Idempotent ALTER-TABLE guard for scope + evidence on entity (ADR-020 D4).

    Called after executescript(_MEMORY_SCHEMA) in init_memory_schema.
    Fresh DBs already have both columns; pre-P2.4 DBs need the ALTER.
    SQLite backfills DEFAULT values into existing rows.
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(entity)")}
    if "scope" not in cols:
        conn.execute("ALTER TABLE entity ADD COLUMN scope TEXT NOT NULL DEFAULT 'personal'")
    if "evidence" not in cols:
        conn.execute("ALTER TABLE entity ADD COLUMN evidence TEXT NOT NULL DEFAULT '{}'")


def _ensure_hypothesis_topic_tags(conn: sqlite3.Connection) -> None:
    """Idempotent ALTER-TABLE guard for the topic_tags column (ADR-018 D5).

    Called after executescript(_MEMORY_SCHEMA) in init_memory_schema.
    Fresh DBs already have the column via CREATE TABLE; pre-P2.1 DBs need
    the ALTER. SQLite backfills the DEFAULT '[]' constant into existing rows.
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(hypothesis)")}
    if "topic_tags" not in cols:
        conn.execute("ALTER TABLE hypothesis ADD COLUMN topic_tags TEXT NOT NULL DEFAULT '[]'")


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
    _ensure_entity_columns(conn)
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
    topic_tags: list[str] | None = None,
) -> Hypothesis:
    """Insert a new Hypothesis row. Pure producer — does NOT touch event_store.

    Caller chooses whether to also emit a `hypothesis` event into the
    event stream (if at all). Memory table and event stream are NOT
    auto-synced. Per ADR-016 D4.

    topic_tags (optional, keyword-only): proposed tags. Normalized + auto-
    registered via resolve_tags inside the write transaction (ADR-018 D4 +
    D6). Existing callers omit this and get topic_tags=[].

    Raises:
        pydantic.ValidationError: if any field fails schema validation
            (e.g., confidence out of [0.0, 1.0], source_event_ids empty,
            content empty, room_id FK failure).
        EventNotFoundError: if any source_event_id is absent from the
            event store (per ADR-016 D2 producer-time existence check,
            Y2 alpha-(ii) routing).
        ValueError: if any proposed tag normalizes to "" (ADR-018 D4 D6).
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
            resolution = resolve_tags(topic_tags or [], conn, now=ts)
            conn.execute(
                """INSERT INTO hypothesis
                       (id, content, room_id, confidence, source_event_ids,
                        status, candidate_for_promotion, topic_tags, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    hyp.id,
                    hyp.content,
                    str(hyp.room_id),
                    hyp.confidence,
                    json.dumps(list(hyp.source_event_ids)),
                    hyp.status.value,
                    int(hyp.candidate_for_promotion),
                    json.dumps(resolution.canonical),
                    hyp.created_at,
                ),
            )
    except sqlite3.Error as exc:
        raise MemoryStoreError(f"failed to insert hypothesis: {exc}") from exc

    return hyp.model_copy(update={"topic_tags": resolution.canonical})


# ---------------------------------------------------------------------------
# Hypothesis tag updater (P2.6 / ADR-022 D6)
# ---------------------------------------------------------------------------


def update_hypothesis_tags(
    hyp_id: HypothesisId,
    *,
    topic_tags: list[str],
    conn: sqlite3.Connection,
) -> Hypothesis:
    """Overwrite a hypothesis row's topic_tags with *topic_tags*.

    Routes proposed raw tags through ``resolve_tags`` (normalizes +
    registers) then UPDATEs the hypothesis row's ``topic_tags`` column
    with the JSON-serialised canonical list.

    Semantics: OVERWRITE (latest-wins). A second call with different tags
    REPLACES the stored tags entirely — no merge/append.

    Args:
        hyp_id: Id of the hypothesis to update.
        topic_tags: Raw proposed tags. Normalized + auto-registered via
            ``resolve_tags``. May be empty (clears tags).
        conn: SQLite connection. Must already have memory schema
            initialised. Uses ``with conn:`` transaction.

    Returns:
        The updated ``Hypothesis`` (reloaded from the DB row).

    Raises:
        MemoryStoreError: If the hypothesis is not found, or on any
            unexpected SQLite failure.
        ValueError: If any proposed tag normalizes to "" (whitespace-only
            / empty input — per ADR-018 D4 fail-loud contract).
    """
    try:
        with conn:
            resolution = resolve_tags(topic_tags, conn)
            result = conn.execute(
                "UPDATE hypothesis SET topic_tags = ? WHERE id = ?",
                (json.dumps(resolution.canonical), hyp_id),
            )
            if result.rowcount == 0:
                raise MemoryStoreError(f"hypothesis not found: {hyp_id!r}")
    except sqlite3.Error as exc:
        raise MemoryStoreError(f"failed to update hypothesis tags: {exc}") from exc

    updated = get_hypothesis_by_id(hyp_id, conn=conn)
    if updated is None:
        raise MemoryStoreError(f"hypothesis not found after update: {hyp_id!r}")
    return updated


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


def _row_to_entity(row: sqlite3.Row) -> Entity:
    return Entity(
        id=EntityId(row["id"]),
        type=EntityType(row["type"]),
        attributes=json.loads(row["attributes"]),
        scope=EntityScope(row["scope"]),
        evidence=json.loads(row["evidence"]),
        created_at=TimestampMs(row["created_at"]),
    )


def _row_to_project_archive(row: sqlite3.Row) -> ProjectArchive:
    return ProjectArchive(
        room_id=RoomId(row["room_id"]),
        title=row["title"],
        duration_ms=row["duration_ms"],
        one_line_summary=row["one_line_summary"],
        decision_log=json.loads(row["decision_log"]),
        spinoff_questions=json.loads(row["spinoff_questions"]),
        scope=EntityScope(row["scope"]),
        evidence=json.loads(row["evidence"]),
        created_at=TimestampMs(row["created_at"]),
    )
