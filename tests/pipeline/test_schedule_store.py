"""Tests for pipeline_schedules store functions (ADR-042 D2 / P5.1b-2).

Covers:
- round-trip CRUD (create → get → list → delete)
- list_due_schedules: only enabled=1 AND next_fire <= now
- disabled schedules excluded from due query
- future schedules excluded from due query
- update_schedule_next_fire persists
- set_schedule_enabled persists
"""

from __future__ import annotations

import sqlite3

import pytest

from orchestrator.pipeline.store import (
    create_schedule,
    delete_schedule,
    disable_schedule_email,
    get_schedule,
    init_pipeline_schema,
    list_due_schedules,
    list_schedules_for_pipeline,
    promote_schedule_email_live,
    set_schedule_email_optin,
    set_schedule_enabled,
    update_schedule_next_fire,
)


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    init_pipeline_schema(c)
    return c


_PIPE_ID = "pipe_test"
_OWNER = "user_a"
_NOW = 1_700_000_000_000  # fixed epoch-ms


def _make_schedule(
    conn: sqlite3.Connection,
    *,
    pipeline_id: str = _PIPE_ID,
    owner: str = _OWNER,
    kind: str = "interval",
    expr: str = "60",
    next_fire: int = _NOW - 1,  # default: due
) -> str:
    record = create_schedule(
        conn,
        pipeline_id=pipeline_id,
        owner_user_id=owner,
        kind=kind,
        expr=expr,
        next_fire=next_fire,
    )
    return record.schedule_id


# ---------------------------------------------------------------------------
# create / get round-trip
# ---------------------------------------------------------------------------


def test_create_and_get_roundtrip(conn: sqlite3.Connection) -> None:
    sid = _make_schedule(conn, next_fire=12345)
    record = get_schedule(conn, sid)
    assert record is not None
    assert record.schedule_id == sid
    assert record.pipeline_id == _PIPE_ID
    assert record.owner_user_id == _OWNER
    assert record.kind == "interval"
    assert record.expr == "60"
    assert record.next_fire == 12345
    assert record.enabled is True


def test_get_missing_returns_none(conn: sqlite3.Connection) -> None:
    assert get_schedule(conn, "nonexistent") is None


def test_schedule_id_has_psch_prefix(conn: sqlite3.Connection) -> None:
    sid = _make_schedule(conn)
    assert sid.startswith("psch_")


# ---------------------------------------------------------------------------
# list_schedules_for_pipeline
# ---------------------------------------------------------------------------


def test_list_schedules_for_pipeline_empty(conn: sqlite3.Connection) -> None:
    assert list_schedules_for_pipeline(conn, _PIPE_ID) == []


def test_list_schedules_for_pipeline_multiple(conn: sqlite3.Connection) -> None:
    sid1 = _make_schedule(conn, expr="60")
    sid2 = _make_schedule(conn, expr="120")
    records = list_schedules_for_pipeline(conn, _PIPE_ID)
    assert {r.schedule_id for r in records} == {sid1, sid2}


def test_list_schedules_filters_by_pipeline(conn: sqlite3.Connection) -> None:
    sid_a = _make_schedule(conn, pipeline_id="pipe_a")
    _make_schedule(conn, pipeline_id="pipe_b")
    records = list_schedules_for_pipeline(conn, "pipe_a")
    assert len(records) == 1
    assert records[0].schedule_id == sid_a


# ---------------------------------------------------------------------------
# list_due_schedules
# ---------------------------------------------------------------------------


def test_list_due_schedules_returns_due_enabled(conn: sqlite3.Connection) -> None:
    sid = _make_schedule(conn, next_fire=_NOW - 1)
    due = list_due_schedules(conn, _NOW)
    assert any(r.schedule_id == sid for r in due)


def test_list_due_schedules_excludes_future(conn: sqlite3.Connection) -> None:
    _make_schedule(conn, next_fire=_NOW + 1000)
    due = list_due_schedules(conn, _NOW)
    assert due == []


def test_list_due_schedules_excludes_disabled(conn: sqlite3.Connection) -> None:
    sid = _make_schedule(conn, next_fire=_NOW - 1)
    set_schedule_enabled(conn, sid, False)
    due = list_due_schedules(conn, _NOW)
    assert due == []


def test_list_due_schedules_exact_boundary(conn: sqlite3.Connection) -> None:
    """next_fire == now_ms is due (<=)."""
    sid = _make_schedule(conn, next_fire=_NOW)
    due = list_due_schedules(conn, _NOW)
    assert any(r.schedule_id == sid for r in due)


def test_list_due_schedules_mixed(conn: sqlite3.Connection) -> None:
    due_sid = _make_schedule(conn, expr="60", next_fire=_NOW - 1)
    _make_schedule(conn, expr="120", next_fire=_NOW + 5000)
    disabled_sid = _make_schedule(conn, expr="180", next_fire=_NOW - 1)
    set_schedule_enabled(conn, disabled_sid, False)

    due = list_due_schedules(conn, _NOW)
    sids = {r.schedule_id for r in due}
    assert due_sid in sids
    assert disabled_sid not in sids


# ---------------------------------------------------------------------------
# update_schedule_next_fire
# ---------------------------------------------------------------------------


def test_update_next_fire_persists(conn: sqlite3.Connection) -> None:
    sid = _make_schedule(conn, next_fire=100)
    update_schedule_next_fire(conn, sid, 999_999)
    record = get_schedule(conn, sid)
    assert record is not None
    assert record.next_fire == 999_999


def test_update_next_fire_moves_out_of_due(conn: sqlite3.Connection) -> None:
    sid = _make_schedule(conn, next_fire=_NOW - 1)
    update_schedule_next_fire(conn, sid, _NOW + 60_000)
    due = list_due_schedules(conn, _NOW)
    assert not any(r.schedule_id == sid for r in due)


# ---------------------------------------------------------------------------
# set_schedule_enabled / delete
# ---------------------------------------------------------------------------


def test_set_schedule_enabled_false_then_true(conn: sqlite3.Connection) -> None:
    sid = _make_schedule(conn)
    set_schedule_enabled(conn, sid, False)
    assert get_schedule(conn, sid) is not None
    assert get_schedule(conn, sid).enabled is False  # type: ignore[union-attr]
    set_schedule_enabled(conn, sid, True)
    assert get_schedule(conn, sid).enabled is True  # type: ignore[union-attr]


def test_delete_schedule(conn: sqlite3.Connection) -> None:
    sid = _make_schedule(conn)
    delete_schedule(conn, sid)
    assert get_schedule(conn, sid) is None


# ---------------------------------------------------------------------------
# P5.1c-1: email opt-in 3-state columns + guarded migration (ADR-043 D5)
# ---------------------------------------------------------------------------


def test_fresh_db_email_columns_default_off(conn: sqlite3.Connection) -> None:
    """A fresh DB has all three email columns with OFF defaults."""
    sid = _make_schedule(conn)
    record = get_schedule(conn, sid)
    assert record is not None
    assert record.email_enabled is False
    assert record.email_mode == "dry_run"
    assert record.email_recipient is None


def test_create_schedule_defaults_email_off(conn: sqlite3.Connection) -> None:
    """create_schedule returns a record with email defaults OFF."""
    from orchestrator.pipeline.store import create_schedule as _cs

    record = _cs(
        conn,
        pipeline_id=_PIPE_ID,
        owner_user_id=_OWNER,
        kind="interval",
        expr="60",
        next_fire=_NOW,
    )
    assert record.email_enabled is False
    assert record.email_mode == "dry_run"
    assert record.email_recipient is None


def test_set_schedule_email_optin_lands_in_dry_run(conn: sqlite3.Connection) -> None:
    """set_schedule_email_optin → email_enabled=True, email_mode='dry_run'."""
    sid = _make_schedule(conn)
    set_schedule_email_optin(conn, sid, recipient="alice@example.com")
    record = get_schedule(conn, sid)
    assert record is not None
    assert record.email_enabled is True
    assert record.email_mode == "dry_run"
    assert record.email_recipient == "alice@example.com"


def test_promote_schedule_email_live(conn: sqlite3.Connection) -> None:
    """promote_schedule_email_live → email_mode='live' (from dry-run)."""
    sid = _make_schedule(conn)
    set_schedule_email_optin(conn, sid, recipient="alice@example.com")
    promote_schedule_email_live(conn, sid)
    record = get_schedule(conn, sid)
    assert record is not None
    assert record.email_enabled is True
    assert record.email_mode == "live"
    assert record.email_recipient == "alice@example.com"


def test_disable_schedule_email(conn: sqlite3.Connection) -> None:
    """disable_schedule_email → email_enabled=False (OFF)."""
    sid = _make_schedule(conn)
    set_schedule_email_optin(conn, sid, recipient="alice@example.com")
    promote_schedule_email_live(conn, sid)
    disable_schedule_email(conn, sid)
    record = get_schedule(conn, sid)
    assert record is not None
    assert record.email_enabled is False


def test_email_optin_idempotent_re_init(conn: sqlite3.Connection) -> None:
    """Re-calling init_pipeline_schema on a DB that already has email columns is a no-op."""
    sid = _make_schedule(conn)
    set_schedule_email_optin(conn, sid, recipient="bob@example.com")
    # Second init must not wipe data or raise
    init_pipeline_schema(conn)
    record = get_schedule(conn, sid)
    assert record is not None
    assert record.email_recipient == "bob@example.com"


def test_pre_existing_db_migration_adds_email_columns() -> None:
    """Pre-existing DB (without email columns) migrates cleanly; rows default to email OFF."""
    c = sqlite3.connect(":memory:")
    # Create schema WITHOUT the email columns (simulates a pre-P5.1c DB).
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS pipeline_schedules (
            schedule_id   TEXT PRIMARY KEY,
            pipeline_id   TEXT NOT NULL,
            owner_user_id TEXT NOT NULL,
            kind          TEXT NOT NULL,
            expr          TEXT NOT NULL,
            next_fire     INTEGER NOT NULL,
            enabled       INTEGER NOT NULL DEFAULT 1,
            created_at    INTEGER NOT NULL
        );
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
    )
    # Insert a pre-existing row without email columns
    c.execute(
        "INSERT INTO pipeline_schedules"
        " (schedule_id, pipeline_id, owner_user_id, kind, expr, next_fire, enabled, created_at)"
        " VALUES ('psch_old', 'pipe_x', 'user_x', 'interval', '60', 0, 1, 0)"
    )
    c.commit()

    # Run migration
    init_pipeline_schema(c)

    # Existing row defaults to email OFF
    record = get_schedule(c, "psch_old")
    assert record is not None
    assert record.email_enabled is False
    assert record.email_mode == "dry_run"
    assert record.email_recipient is None

    # Columns now present (verifiable via new records too)
    sid2 = _make_schedule(c)
    r2 = get_schedule(c, sid2)
    assert r2 is not None
    assert r2.email_enabled is False


def test_list_schedules_includes_email_fields(conn: sqlite3.Connection) -> None:
    """list_schedules_for_pipeline and list_due_schedules populate email fields."""
    sid = _make_schedule(conn, next_fire=_NOW - 1)
    set_schedule_email_optin(conn, sid, recipient="x@y.com")
    promote_schedule_email_live(conn, sid)

    listed = list_schedules_for_pipeline(conn, _PIPE_ID)
    assert len(listed) == 1
    r = listed[0]
    assert r.email_enabled is True
    assert r.email_mode == "live"
    assert r.email_recipient == "x@y.com"

    due = list_due_schedules(conn, _NOW)
    assert len(due) == 1
    r2 = due[0]
    assert r2.email_enabled is True
    assert r2.email_mode == "live"
