"""Entity create/read API + Preference API for cross-room memory.

Per ADR-020 D1 (entity surface) + D2 (preference upsert, Principle-11).

record_entity: plain-insert / append-only deterministic sink for
  explicit/factual or code-derived entities. Rejects type=PREFERENCE
  (use record_preference instead — closes the Principle-11 bypass path).

record_preference: upserts by (user_id, key, scope); requires user_id
  so an LLM-inferred preference with no declaring user is un-representable.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from orchestrator.core.event import TimestampMs, now_ms
from orchestrator.memory.schema import (
    Entity,
    EntityId,
    EntityScope,
    EntityType,
    generate_entity_id,
)
from orchestrator.memory.store import _row_to_entity


def record_entity(
    type: EntityType,
    attributes: dict[str, Any],
    *,
    scope: EntityScope = EntityScope.PERSONAL,
    evidence: dict[str, Any] | None = None,
    conn: sqlite3.Connection,
    now: TimestampMs | None = None,
) -> Entity:
    """Plain-insert an entity row. Append-only — duplicate calls create distinct rows.

    Raises ValueError if type == PREFERENCE (use record_preference for preferences).
    """
    if type == EntityType.PREFERENCE:
        raise ValueError(
            "record_entity rejects type=PREFERENCE; use record_preference(user_id=...) instead"
        )
    ts = now if now is not None else now_ms()
    ev = evidence if evidence is not None else {}
    entity = Entity(
        id=generate_entity_id(),
        type=type,
        attributes=attributes,
        scope=scope,
        evidence=ev,
        created_at=ts,
    )
    with conn:
        conn.execute(
            """INSERT INTO entity (id, type, attributes, scope, evidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entity.id,
                entity.type.value,
                json.dumps(dict(entity.attributes)),
                entity.scope.value,
                json.dumps(dict(entity.evidence)),
                entity.created_at,
            ),
        )
    return entity


def get_entity_by_id(
    entity_id: EntityId,
    conn: sqlite3.Connection,
) -> Entity | None:
    """Load a single entity by id. Returns None if absent."""
    row = conn.execute("SELECT * FROM entity WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        return None
    return _row_to_entity(row)


def list_entities(
    *,
    type: EntityType | None = None,
    scope: EntityScope | None = None,
    conn: sqlite3.Connection,
) -> list[Entity]:
    """Return entities ordered by id ASC. Optionally filter by type and/or scope."""
    sql = "SELECT * FROM entity"
    params: list[str] = []
    conditions: list[str] = []
    if type is not None:
        conditions.append("type = ?")
        params.append(type.value)
    if scope is not None:
        conditions.append("scope = ?")
        params.append(scope.value)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY id ASC"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_entity(row) for row in rows]


def record_preference(
    key: str,
    value: str,
    user_id: str,
    *,
    scope: EntityScope = EntityScope.PERSONAL,
    conn: sqlite3.Connection,
    now: TimestampMs | None = None,
) -> Entity:
    """Upsert a preference by (user_id, key, scope). Requires non-empty user_id.

    Exactly one row per (user_id, key, scope); a re-declaration updates the value
    in place (latest-wins). Writes type=PREFERENCE, evidence={"declared_by": user_id}.
    An LLM-inferred preference with no declaring user is un-representable
    (ADR-020 D2, Principle 11).
    """
    if not user_id:
        raise ValueError("user_id must be non-empty (explicit declaring/confirming user required)")
    ts = now if now is not None else now_ms()

    new_attrs = {"key": key, "value": value}
    new_evidence = {"declared_by": user_id}

    # Read-modify-write: scan preferences with matching scope, filter in Python (no JSON1).
    existing_id: EntityId | None = None
    rows = conn.execute(
        "SELECT * FROM entity WHERE type = ? AND scope = ?",
        (EntityType.PREFERENCE.value, scope.value),
    ).fetchall()
    for row in rows:
        attrs = json.loads(row["attributes"])
        ev = json.loads(row["evidence"])
        if attrs.get("key") == key and ev.get("declared_by") == user_id:
            existing_id = EntityId(row["id"])
            break

    if existing_id is not None:
        with conn:
            conn.execute(
                "UPDATE entity SET attributes = ?, evidence = ?, created_at = ? WHERE id = ?",
                (json.dumps(new_attrs), json.dumps(new_evidence), ts, existing_id),
            )
        return Entity(
            id=existing_id,
            type=EntityType.PREFERENCE,
            attributes=new_attrs,
            scope=scope,
            evidence=new_evidence,
            created_at=ts,
        )

    eid = generate_entity_id()
    entity = Entity(
        id=eid,
        type=EntityType.PREFERENCE,
        attributes=new_attrs,
        scope=scope,
        evidence=new_evidence,
        created_at=ts,
    )
    with conn:
        conn.execute(
            """INSERT INTO entity (id, type, attributes, scope, evidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                eid,
                EntityType.PREFERENCE.value,
                json.dumps(new_attrs),
                scope.value,
                json.dumps(new_evidence),
                ts,
            ),
        )
    return entity


def list_preferences(
    *,
    user_id: str | None = None,
    scope: EntityScope | None = None,
    conn: sqlite3.Connection,
) -> list[Entity]:
    """Return preferences (type=PREFERENCE) ordered by id ASC.

    Thin wrapper over list_entities(type=PREFERENCE). Optionally filter by
    user_id (evidence.declared_by, filtered in Python) and/or scope.
    """
    entities = list_entities(type=EntityType.PREFERENCE, scope=scope, conn=conn)
    if user_id is None:
        return entities
    return [e for e in entities if e.evidence.get("declared_by") == user_id]
