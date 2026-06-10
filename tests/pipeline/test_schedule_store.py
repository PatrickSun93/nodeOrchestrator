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
    get_schedule,
    init_pipeline_schema,
    list_due_schedules,
    list_schedules_for_pipeline,
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
