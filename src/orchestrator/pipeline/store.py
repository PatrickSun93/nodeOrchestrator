"""Pipeline definition + run-index persistence (ADR-041 D8).

Side tables co-located in the main DB, following the users/sessions precedent
(api/auth/users.py:30-67). CREATE TABLE IF NOT EXISTS is idempotent.

No schedule columns (cron/interval/next_fire) — those are P5.1b (ADR-041 D10).
"""

from __future__ import annotations

import sqlite3
import time
import uuid

from orchestrator.pipeline.schema import (
    PipelineDefinition,
    PipelineRecord,
    PipelineRunRecord,
)

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

PIPELINE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipelines (
    pipeline_id   TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    definition    TEXT NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id        TEXT PRIMARY KEY,
    pipeline_id   TEXT NOT NULL,
    room_id       TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    started_at    INTEGER NOT NULL,
    status        TEXT NOT NULL
);
"""


def init_pipeline_schema(conn: sqlite3.Connection) -> None:
    """Create pipelines and pipeline_runs tables if not present (idempotent).

    Called by _build_context alongside init_auth_schema (ADR-041 D8).
    """
    conn.executescript(PIPELINE_SCHEMA)
    conn.commit()


# ---------------------------------------------------------------------------
# Pipeline definition CRUD
# ---------------------------------------------------------------------------


def create_pipeline(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    definition: PipelineDefinition,
) -> PipelineRecord:
    """Insert a new pipeline definition.  Raises ValueError on duplicate id."""
    pipeline_id = f"pipe_{uuid.uuid4().hex}"
    created_at = int(time.time() * 1000)
    definition_json = definition.model_dump_json()
    try:
        conn.execute(
            "INSERT INTO pipelines (pipeline_id, owner_user_id, definition, enabled, created_at)"
            " VALUES (?, ?, ?, 1, ?)",
            (pipeline_id, owner_user_id, definition_json, created_at),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"pipeline_id {pipeline_id!r} already exists") from exc
    return PipelineRecord(
        pipeline_id=pipeline_id,
        owner_user_id=owner_user_id,
        definition=definition,
        enabled=True,
        created_at=created_at,
    )


def get_pipeline(conn: sqlite3.Connection, pipeline_id: str) -> PipelineRecord | None:
    """Fetch one pipeline definition by id.  Returns None if not found."""
    row = conn.execute(
        "SELECT pipeline_id, owner_user_id, definition, enabled, created_at"
        " FROM pipelines WHERE pipeline_id = ?",
        (pipeline_id,),
    ).fetchone()
    if row is None:
        return None
    pid, owner, defn_json, enabled, created_at = row
    definition = PipelineDefinition.model_validate_json(defn_json)
    return PipelineRecord(
        pipeline_id=pid,
        owner_user_id=owner,
        definition=definition,
        enabled=bool(enabled),
        created_at=created_at,
    )


def list_pipelines(conn: sqlite3.Connection, owner_user_id: str) -> list[PipelineRecord]:
    """List all pipeline definitions owned by owner_user_id."""
    rows = conn.execute(
        "SELECT pipeline_id, owner_user_id, definition, enabled, created_at"
        " FROM pipelines WHERE owner_user_id = ? ORDER BY created_at ASC",
        (owner_user_id,),
    ).fetchall()
    results = []
    for pid, owner, defn_json, enabled, created_at in rows:
        definition = PipelineDefinition.model_validate_json(defn_json)
        results.append(
            PipelineRecord(
                pipeline_id=pid,
                owner_user_id=owner,
                definition=definition,
                enabled=bool(enabled),
                created_at=created_at,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Run index
# ---------------------------------------------------------------------------


def create_pipeline_run(
    conn: sqlite3.Connection,
    *,
    pipeline_id: str,
    room_id: str,
    owner_user_id: str,
    status: str = "running",
) -> PipelineRunRecord:
    """Insert a pipeline_runs index row for a new run."""
    run_id = f"prun_{uuid.uuid4().hex}"
    started_at = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO pipeline_runs"
        " (run_id, pipeline_id, room_id, owner_user_id, started_at, status)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, pipeline_id, room_id, owner_user_id, started_at, status),
    )
    conn.commit()
    return PipelineRunRecord(
        run_id=run_id,
        pipeline_id=pipeline_id,
        room_id=room_id,
        owner_user_id=owner_user_id,
        started_at=started_at,
        status=status,
    )


def update_pipeline_run_status(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
) -> None:
    """Update the status of an existing pipeline run."""
    conn.execute(
        "UPDATE pipeline_runs SET status = ? WHERE run_id = ?",
        (status, run_id),
    )
    conn.commit()
