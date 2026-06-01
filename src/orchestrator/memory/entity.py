"""Entity create/read API for cross-room memory. Per ADR-020 D1.

record_entity: plain-insert / append-only deterministic sink for
  explicit/factual or code-derived entities. Rejects type=PREFERENCE
  (use record_preference instead — closes the Principle-11 bypass path).

Preference API (record_preference, list_preferences) ships in P2.4-4 (same file).
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
