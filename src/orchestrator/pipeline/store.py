"""Pipeline definition + run-index + schedule persistence (ADR-041 D8 / ADR-042 D2 / ADR-043 D5).

Side tables co-located in the main DB, following the users/sessions precedent
(api/auth/users.py:30-67). CREATE TABLE IF NOT EXISTS is idempotent.

P5.1b adds the pipeline_schedules side table (ADR-042 D2).
P5.1c adds email opt-in columns via guarded ALTER (ADR-043 D5).
"""

from __future__ import annotations

import sqlite3
import time
import uuid

from orchestrator.pipeline.schema import (
    PipelineDefinition,
    PipelineRecord,
    PipelineRunRecord,
    PipelineScheduleRecord,
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

CREATE TABLE IF NOT EXISTS pipeline_schedules (
    schedule_id      TEXT PRIMARY KEY,
    pipeline_id      TEXT NOT NULL,
    owner_user_id    TEXT NOT NULL,
    kind             TEXT NOT NULL,
    expr             TEXT NOT NULL,
    next_fire        INTEGER NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       INTEGER NOT NULL,
    email_enabled    INTEGER NOT NULL DEFAULT 0,
    email_mode       TEXT NOT NULL DEFAULT 'dry_run',
    email_recipient  TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_schedules_due
    ON pipeline_schedules (enabled, next_fire)
    WHERE enabled = 1;
"""


def _ensure_schedule_email_columns(conn: sqlite3.Connection) -> None:
    """Idempotent ALTER-TABLE guard for email opt-in columns (ADR-043 D5).

    Called after executescript(PIPELINE_SCHEMA) in init_pipeline_schema.
    Fresh DBs already have all columns from CREATE TABLE; pre-P5.1c DBs
    need the ALTER. SQLite backfills DEFAULT values into existing rows.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_schedules)")}
    if "email_enabled" not in cols:
        conn.execute(
            "ALTER TABLE pipeline_schedules ADD COLUMN email_enabled INTEGER NOT NULL DEFAULT 0"
        )
    if "email_mode" not in cols:
        conn.execute(
            "ALTER TABLE pipeline_schedules ADD COLUMN email_mode TEXT NOT NULL DEFAULT 'dry_run'"
        )
    if "email_recipient" not in cols:
        conn.execute("ALTER TABLE pipeline_schedules ADD COLUMN email_recipient TEXT")


def init_pipeline_schema(conn: sqlite3.Connection) -> None:
    """Create pipelines and pipeline_runs tables if not present (idempotent).

    Called by _build_context alongside init_auth_schema (ADR-041 D8).
    """
    conn.executescript(PIPELINE_SCHEMA)
    _ensure_schedule_email_columns(conn)
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
    run_id: str | None = None,
) -> PipelineRunRecord:
    """Insert a pipeline_runs index row for a new run.

    If run_id is supplied (caller-generated), it is used as-is so the store row id
    matches the id embedded in the run-anchor event (F-runid correlation).
    """
    if run_id is None:
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


# ---------------------------------------------------------------------------
# Schedule CRUD (ADR-042 D2 / P5.1b-2)
# ---------------------------------------------------------------------------


def create_schedule(
    conn: sqlite3.Connection,
    *,
    pipeline_id: str,
    owner_user_id: str,
    kind: str,
    expr: str,
    next_fire: int,
) -> PipelineScheduleRecord:
    """Insert a new pipeline schedule row; returns the created record.

    Email opt-in defaults OFF (email_enabled=0, email_mode='dry_run', email_recipient=NULL).
    """
    schedule_id = f"psch_{uuid.uuid4().hex}"
    created_at = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO pipeline_schedules"
        " (schedule_id, pipeline_id, owner_user_id, kind, expr, next_fire, enabled, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
        (schedule_id, pipeline_id, owner_user_id, kind, expr, next_fire, created_at),
    )
    conn.commit()
    return PipelineScheduleRecord(
        schedule_id=schedule_id,
        pipeline_id=pipeline_id,
        owner_user_id=owner_user_id,
        kind=kind,
        expr=expr,
        next_fire=next_fire,
        enabled=True,
        created_at=created_at,
        email_enabled=False,
        email_mode="dry_run",
        email_recipient=None,
    )


def get_schedule(
    conn: sqlite3.Connection,
    schedule_id: str,
) -> PipelineScheduleRecord | None:
    """Fetch one schedule by schedule_id.  Returns None if not found."""
    row = conn.execute(
        "SELECT schedule_id, pipeline_id, owner_user_id, kind, expr, next_fire, enabled,"
        " created_at, email_enabled, email_mode, email_recipient"
        " FROM pipeline_schedules WHERE schedule_id = ?",
        (schedule_id,),
    ).fetchone()
    if row is None:
        return None
    sid, pid, owner, kind, expr, next_fire, enabled, created_at, em_en, em_mode, em_recip = row
    return PipelineScheduleRecord(
        schedule_id=sid,
        pipeline_id=pid,
        owner_user_id=owner,
        kind=kind,
        expr=expr,
        next_fire=next_fire,
        enabled=bool(enabled),
        created_at=created_at,
        email_enabled=bool(em_en),
        email_mode=em_mode,
        email_recipient=em_recip,
    )


def list_schedules_for_pipeline(
    conn: sqlite3.Connection,
    pipeline_id: str,
) -> list[PipelineScheduleRecord]:
    """List all schedules for a given pipeline, ordered by created_at."""
    rows = conn.execute(
        "SELECT schedule_id, pipeline_id, owner_user_id, kind, expr, next_fire, enabled,"
        " created_at, email_enabled, email_mode, email_recipient"
        " FROM pipeline_schedules WHERE pipeline_id = ? ORDER BY created_at ASC",
        (pipeline_id,),
    ).fetchall()
    return [
        PipelineScheduleRecord(
            schedule_id=sid,
            pipeline_id=pid,
            owner_user_id=owner,
            kind=kind,
            expr=expr,
            next_fire=next_fire,
            enabled=bool(enabled),
            created_at=created_at,
            email_enabled=bool(em_en),
            email_mode=em_mode,
            email_recipient=em_recip,
        )
        for (
            sid,
            pid,
            owner,
            kind,
            expr,
            next_fire,
            enabled,
            created_at,
            em_en,
            em_mode,
            em_recip,
        ) in rows
    ]


def list_due_schedules(
    conn: sqlite3.Connection,
    now_ms: int,
) -> list[PipelineScheduleRecord]:
    """Return enabled schedules whose next_fire is at or before now_ms.

    Discovery query for the reader path (ADR-042 D4).  Results are approximate
    (stale reader); the sweeper act re-checks authoritatively on the writer.
    """
    rows = conn.execute(
        "SELECT schedule_id, pipeline_id, owner_user_id, kind, expr, next_fire, enabled,"
        " created_at, email_enabled, email_mode, email_recipient"
        " FROM pipeline_schedules WHERE enabled = 1 AND next_fire <= ?",
        (now_ms,),
    ).fetchall()
    return [
        PipelineScheduleRecord(
            schedule_id=sid,
            pipeline_id=pid,
            owner_user_id=owner,
            kind=kind,
            expr=expr,
            next_fire=next_fire,
            enabled=bool(enabled),
            created_at=created_at,
            email_enabled=bool(em_en),
            email_mode=em_mode,
            email_recipient=em_recip,
        )
        for (
            sid,
            pid,
            owner,
            kind,
            expr,
            next_fire,
            enabled,
            created_at,
            em_en,
            em_mode,
            em_recip,
        ) in rows
    ]


def update_schedule_next_fire(
    conn: sqlite3.Connection,
    schedule_id: str,
    next_fire: int,
) -> None:
    """Advance next_fire for a schedule (claim step in ADR-042 D4 step 3)."""
    conn.execute(
        "UPDATE pipeline_schedules SET next_fire = ? WHERE schedule_id = ?",
        (next_fire, schedule_id),
    )
    conn.commit()


def set_schedule_enabled(
    conn: sqlite3.Connection,
    schedule_id: str,
    enabled: bool,
) -> None:
    """Enable or disable a schedule."""
    conn.execute(
        "UPDATE pipeline_schedules SET enabled = ? WHERE schedule_id = ?",
        (1 if enabled else 0, schedule_id),
    )
    conn.commit()


def set_schedule_email_optin(
    conn: sqlite3.Connection,
    schedule_id: str,
    *,
    recipient: str,
) -> None:
    """Opt a schedule in to headless email (→ DRY-RUN state, ADR-043 D5/D6).

    Sets email_enabled=1, email_mode='dry_run', email_recipient=recipient.
    Enabling always lands in dry-run; promote_schedule_email_live is the
    explicit second action to reach live.
    """
    conn.execute(
        "UPDATE pipeline_schedules"
        " SET email_enabled=1, email_mode='dry_run', email_recipient=?"
        " WHERE schedule_id=?",
        (recipient, schedule_id),
    )
    conn.commit()


def promote_schedule_email_live(
    conn: sqlite3.Connection,
    schedule_id: str,
) -> None:
    """Promote a schedule's email opt-in from dry-run → live (ADR-043 D5/D6).

    Sets email_mode='live'; only meaningful when email_enabled=1.
    """
    conn.execute(
        "UPDATE pipeline_schedules SET email_mode='live' WHERE schedule_id=?",
        (schedule_id,),
    )
    conn.commit()


def disable_schedule_email(
    conn: sqlite3.Connection,
    schedule_id: str,
) -> None:
    """Disable email opt-in for a schedule (→ OFF state, ADR-043 D5)."""
    conn.execute(
        "UPDATE pipeline_schedules SET email_enabled=0 WHERE schedule_id=?",
        (schedule_id,),
    )
    conn.commit()


def delete_schedule(
    conn: sqlite3.Connection,
    schedule_id: str,
) -> None:
    """Delete a schedule row."""
    conn.execute(
        "DELETE FROM pipeline_schedules WHERE schedule_id = ?",
        (schedule_id,),
    )
    conn.commit()
