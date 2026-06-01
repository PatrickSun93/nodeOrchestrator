"""ProjectArchive create/read API for cross-room memory. Per ADR-020 D3.

ProjectArchive is a persisted post-close narrative identity for a room.
The semantic fields (one_line_summary, spinoff_questions) are produced
outside memory/ and passed in; memory/ persists, never generates (Principle 5).
The decision_log is a frozen serialized copy composed at close by the caller.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from orchestrator.core.event import RoomId, TimestampMs, now_ms
from orchestrator.memory.schema import (
    EntityScope,
    ProjectArchive,
)
from orchestrator.memory.store import _row_to_project_archive


def record_project_archive(
    room_id: RoomId,
    title: str,
    duration_ms: int,
    one_line_summary: str,
    decision_log: list[dict[str, Any]],
    spinoff_questions: list[str],
    *,
    scope: EntityScope = EntityScope.PROJECT,
    evidence: dict[str, Any] | None = None,
    conn: sqlite3.Connection,
    now: TimestampMs | None = None,
) -> ProjectArchive:
    """Persist a ProjectArchive for a room. One row per room_id (PK).

    A duplicate room_id raises sqlite3.IntegrityError (fail-loud per ADR-020 D3).
    The caller composes decision_log (via produce_decision_log) and the
    semantic fields before calling here; memory/ stores a frozen copy.
    """
    ts = now if now is not None else now_ms()
    ev = evidence if evidence is not None else {}
    archive = ProjectArchive(
        room_id=room_id,
        title=title,
        duration_ms=duration_ms,
        one_line_summary=one_line_summary,
        decision_log=decision_log,
        spinoff_questions=spinoff_questions,
        scope=scope,
        evidence=ev,
        created_at=ts,
    )
    with conn:
        conn.execute(
            """INSERT INTO project_archive
               (room_id, title, duration_ms, one_line_summary, decision_log,
                spinoff_questions, scope, evidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(archive.room_id),
                archive.title,
                archive.duration_ms,
                archive.one_line_summary,
                json.dumps(list(archive.decision_log)),
                json.dumps(list(archive.spinoff_questions)),
                archive.scope.value,
                json.dumps(dict(archive.evidence)),
                archive.created_at,
            ),
        )
    return archive


def get_project_archive(
    room_id: RoomId,
    conn: sqlite3.Connection,
) -> ProjectArchive | None:
    """Load a ProjectArchive by room_id. Returns None if absent."""
    row = conn.execute(
        "SELECT * FROM project_archive WHERE room_id = ?", (str(room_id),)
    ).fetchone()
    if row is None:
        return None
    return _row_to_project_archive(row)


def list_project_archives(
    *,
    scope: EntityScope | None = None,
    conn: sqlite3.Connection,
) -> list[ProjectArchive]:
    """Return project archives ordered by room_id ASC. Optionally filter by scope."""
    if scope is not None:
        rows = conn.execute(
            "SELECT * FROM project_archive WHERE scope = ? ORDER BY room_id ASC",
            (scope.value,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM project_archive ORDER BY room_id ASC").fetchall()
    return [_row_to_project_archive(row) for row in rows]
