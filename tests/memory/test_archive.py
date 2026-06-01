"""Tests for memory/archive.py — record_project_archive, get/list readers.

Per plan P2.4-5 acceptance criteria and ADR-020 D3.

Coverage standard:
  §1: archive source in archive.py, readers tested cross-module here
      and in test_p2_4_e2e.py.
  §6: no new models in this file (ProjectArchive tested in test_schema.py).
"""

from __future__ import annotations

import sqlite3

import pytest

from orchestrator.core.event import RoomId, TimestampMs, generate_room_id
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.archive import (
    get_project_archive,
    list_project_archives,
    record_project_archive,
)
from orchestrator.memory.schema import EntityScope
from orchestrator.memory.store import init_memory_schema

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return conn


def _seed_room(conn: sqlite3.Connection) -> RoomId:
    store = EventStore(conn)
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


# ---------------------------------------------------------------------------
# record_project_archive
# ---------------------------------------------------------------------------


class TestRecordProjectArchive:
    def test_happy_path_returns_archive(self) -> None:
        conn = _make_conn()
        room_id = _seed_room(conn)
        archive = record_project_archive(
            room_id=room_id,
            title="Test Project",
            duration_ms=7200000,
            one_line_summary="A project about X.",
            decision_log=[{"decision": "use sqlite"}],
            spinoff_questions=["What about Postgres?"],
            conn=conn,
        )
        assert archive.room_id == room_id
        assert archive.title == "Test Project"
        assert archive.duration_ms == 7200000
        assert archive.one_line_summary == "A project about X."
        assert archive.decision_log == [{"decision": "use sqlite"}]
        assert archive.spinoff_questions == ["What about Postgres?"]
        assert archive.scope == EntityScope.PROJECT

    def test_row_persisted(self) -> None:
        conn = _make_conn()
        room_id = _seed_room(conn)
        archive = record_project_archive(
            room_id=room_id,
            title="Persisted",
            duration_ms=0,
            one_line_summary="Summary.",
            decision_log=[],
            spinoff_questions=[],
            conn=conn,
        )
        loaded = get_project_archive(room_id, conn)
        assert loaded is not None
        assert loaded.room_id == archive.room_id
        assert loaded.title == "Persisted"

    def test_duplicate_room_id_raises_integrity_error(self) -> None:
        """Second archive for same room_id raises sqlite3.IntegrityError (fail-loud).

        Discriminating: if archive upserted silently, no error would be raised.
        We assert IntegrityError — this fails if record_project_archive used
        INSERT OR REPLACE or ON CONFLICT DO UPDATE instead of plain INSERT.
        """
        conn = _make_conn()
        room_id = _seed_room(conn)
        record_project_archive(
            room_id=room_id,
            title="First",
            duration_ms=0,
            one_line_summary="S1",
            decision_log=[],
            spinoff_questions=[],
            conn=conn,
        )
        with pytest.raises(sqlite3.IntegrityError):
            record_project_archive(
                room_id=room_id,
                title="Second",
                duration_ms=0,
                one_line_summary="S2",
                decision_log=[],
                spinoff_questions=[],
                conn=conn,
            )

    def test_evidence_stored_and_retrieved(self) -> None:
        conn = _make_conn()
        room_id = _seed_room(conn)
        archive = record_project_archive(
            room_id=room_id,
            title="T",
            duration_ms=0,
            one_line_summary="S",
            decision_log=[],
            spinoff_questions=[],
            evidence={"created_by": "test"},
            conn=conn,
        )
        assert archive.evidence == {"created_by": "test"}
        loaded = get_project_archive(room_id, conn)
        assert loaded is not None
        assert loaded.evidence == {"created_by": "test"}

    def test_minimal_archive_empty_lists(self) -> None:
        conn = _make_conn()
        room_id = _seed_room(conn)
        archive = record_project_archive(
            room_id=room_id,
            title="Minimal",
            duration_ms=0,
            one_line_summary="Min.",
            decision_log=[],
            spinoff_questions=[],
            conn=conn,
        )
        assert archive.decision_log == []
        assert archive.spinoff_questions == []

    def test_scope_override(self) -> None:
        conn = _make_conn()
        room_id = _seed_room(conn)
        archive = record_project_archive(
            room_id=room_id,
            title="T",
            duration_ms=0,
            one_line_summary="S",
            decision_log=[],
            spinoff_questions=[],
            scope=EntityScope.GLOBAL,
            conn=conn,
        )
        assert archive.scope == EntityScope.GLOBAL

    def test_now_override(self) -> None:
        conn = _make_conn()
        room_id = _seed_room(conn)
        ts = TimestampMs(1_700_000_000_000)
        archive = record_project_archive(
            room_id=room_id,
            title="T",
            duration_ms=0,
            one_line_summary="S",
            decision_log=[],
            spinoff_questions=[],
            conn=conn,
            now=ts,
        )
        assert archive.created_at == ts


# ---------------------------------------------------------------------------
# get_project_archive
# ---------------------------------------------------------------------------


class TestGetProjectArchive:
    def test_missing_returns_none(self) -> None:
        conn = _make_conn()
        assert get_project_archive(RoomId("room_nonexistent"), conn) is None

    def test_decision_log_round_trips(self) -> None:
        conn = _make_conn()
        room_id = _seed_room(conn)
        log = [{"decision": "use sqlite", "rationale": "simple"}, {"decision": "freeze models"}]
        record_project_archive(
            room_id=room_id,
            title="T",
            duration_ms=0,
            one_line_summary="S",
            decision_log=log,
            spinoff_questions=[],
            conn=conn,
        )
        loaded = get_project_archive(room_id, conn)
        assert loaded is not None
        assert loaded.decision_log == log

    def test_spinoff_questions_round_trip(self) -> None:
        conn = _make_conn()
        room_id = _seed_room(conn)
        questions = ["Q1?", "Q2?", "Q3?"]
        record_project_archive(
            room_id=room_id,
            title="T",
            duration_ms=100,
            one_line_summary="S",
            decision_log=[],
            spinoff_questions=questions,
            conn=conn,
        )
        loaded = get_project_archive(room_id, conn)
        assert loaded is not None
        assert loaded.spinoff_questions == questions


# ---------------------------------------------------------------------------
# list_project_archives
# ---------------------------------------------------------------------------


class TestListProjectArchives:
    def test_empty_db_returns_empty(self) -> None:
        conn = _make_conn()
        assert list_project_archives(conn=conn) == []

    def test_deterministic_room_id_asc_order(self) -> None:
        """list_project_archives returns rows in room_id ASC order."""
        conn = _make_conn()
        room1 = _seed_room(conn)
        room2 = _seed_room(conn)
        for rid in (room1, room2):
            record_project_archive(
                room_id=rid,
                title=f"Project {rid[-4:]}",
                duration_ms=0,
                one_line_summary="S",
                decision_log=[],
                spinoff_questions=[],
                conn=conn,
            )
        archives = list_project_archives(conn=conn)
        ids = [str(a.room_id) for a in archives]
        assert ids == sorted(ids), f"expected room_id ASC; got {ids}"

    def test_scope_filter(self) -> None:
        conn = _make_conn()
        room1 = _seed_room(conn)
        room2 = _seed_room(conn)
        record_project_archive(
            room_id=room1,
            title="Project scope",
            duration_ms=0,
            one_line_summary="S",
            decision_log=[],
            spinoff_questions=[],
            scope=EntityScope.PROJECT,
            conn=conn,
        )
        record_project_archive(
            room_id=room2,
            title="Global scope",
            duration_ms=0,
            one_line_summary="S",
            decision_log=[],
            spinoff_questions=[],
            scope=EntityScope.GLOBAL,
            conn=conn,
        )
        project_archives = list_project_archives(scope=EntityScope.PROJECT, conn=conn)
        assert len(project_archives) == 1
        assert project_archives[0].title == "Project scope"
