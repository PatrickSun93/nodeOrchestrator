"""Tests for reentry/leave.py — record_leave_marker + generate_and_record_archive.

Coverage standard:
  §1 cross-module — write in reentry/leave.py → reentry_marker table → read via
     get_leave_marker; archive write → project_archive table → get_project_archive.
     Source ≠ sink: record_leave_marker records ts; get_leave_marker reads it back
     (distinct call sites, distinct modules).
  §6 N/A — no new Pydantic models here (ProjectArchive comes from memory/).
  §3 N/A — no subprocess/file handles.
  §4 N/A — no custom exceptions in this atomic.
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import MagicMock

import pytest

from orchestrator.core.event import (
    Event,
    EventType,
    TimestampMs,
    generate_event_id,
    generate_room_id,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import LLMResponse, ModelId, ProviderId, Usage, generate_request_id
from orchestrator.memory.archive import get_project_archive
from orchestrator.memory.store import init_memory_schema
from orchestrator.reentry.leave import (
    LLMRouterProtocol,
    generate_and_record_archive,
    record_leave_marker,
)
from orchestrator.reentry.store import get_leave_marker, init_reentry_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    init_reentry_schema(conn)
    return store, conn


def _seed_room(store: EventStore, conn: sqlite3.Connection) -> tuple[Room, list[Event]]:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    events = []
    for i in range(2):
        evt = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.UTTERANCE,
            author="user",
            timestamp=TimestampMs(1000 + i),
            content=f"msg {i}",
        )
        store.append(evt)
        events.append(evt)
    return room, events


def _mock_router(summary_json: str) -> MagicMock:
    """Return a mock router that responds to ARCHIVE_SUMMARY_RENDER calls."""
    router = MagicMock(spec=LLMRouterProtocol)
    router.call.return_value = LLMResponse(
        request_id=generate_request_id(),
        content=summary_json,
        model_id_requested=ModelId("m1"),
        model_id_used=ModelId("m1"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=10, output_tokens=20),
        latency_ms=5,
        finish_reason="stop",
    )
    return router


_MOCK_SUMMARY = json.dumps(
    {"one_line_summary": "Test archive summary.", "spinoff_questions": ["What next?", "Any risks?"]}
)


# ---------------------------------------------------------------------------
# record_leave_marker
# ---------------------------------------------------------------------------


def test_record_leave_marker_inserts_row() -> None:
    """record_leave_marker persists the timestamp; get_leave_marker reads it back.

    §1 source ≠ sink: record_leave_marker writes; get_leave_marker reads.
    Discriminating: fails if record_leave_marker doesn't write the row.
    """
    store, conn = _make_store()
    room, _ = _seed_room(store, conn)
    ts = TimestampMs(55000)
    record_leave_marker(room.id, "alice", ts, conn=conn)
    result = get_leave_marker(room.id, "alice", conn)
    assert result == ts


def test_record_leave_marker_upserts_latest_wins() -> None:
    """Second call for same (room, user) updates in place — one row, latest ts.

    Discriminating: fails if upsert creates a second row or returns old ts.
    """
    store, conn = _make_store()
    room, _ = _seed_room(store, conn)
    record_leave_marker(room.id, "alice", TimestampMs(1000), conn=conn)
    record_leave_marker(room.id, "alice", TimestampMs(2000), conn=conn)

    result = get_leave_marker(room.id, "alice", conn)
    assert result == TimestampMs(2000)
    row_count = conn.execute("SELECT COUNT(*) FROM reentry_marker").fetchone()[0]
    assert row_count == 1, "upsert must produce exactly one row per (room_id, user_id)"


def test_record_leave_marker_distinct_rooms_distinct_rows() -> None:
    """Different (room, user) pairs each get their own row."""
    store, conn = _make_store()
    room1, _ = _seed_room(store, conn)
    room2, _ = _seed_room(store, conn)
    record_leave_marker(room1.id, "alice", TimestampMs(100), conn=conn)
    record_leave_marker(room2.id, "alice", TimestampMs(200), conn=conn)
    assert get_leave_marker(room1.id, "alice", conn) == TimestampMs(100)
    assert get_leave_marker(room2.id, "alice", conn) == TimestampMs(200)


# ---------------------------------------------------------------------------
# generate_and_record_archive
# ---------------------------------------------------------------------------


def test_generate_and_record_archive_calls_llm_with_archive_summary_render() -> None:
    """generate_and_record_archive calls ARCHIVE_SUMMARY_RENDER (content-gen).

    Discriminating: fails if the LLM is not called with the correct purpose.
    """
    store, conn = _make_store()
    room, events = _seed_room(store, conn)
    router = _mock_router(_MOCK_SUMMARY)

    generate_and_record_archive(
        room.id,
        "Test Room",
        events,
        room,
        start_ts=TimestampMs(1000),
        end_ts=TimestampMs(5000),
        llm_router=router,
        conn=conn,
    )

    router.call.assert_called_once()
    request = router.call.call_args[0][0]
    assert request.purpose == LLMPurpose.ARCHIVE_SUMMARY_RENDER
    assert request.caller_agent_id is None


def test_generate_and_record_archive_persists_to_project_archive_table() -> None:
    """Archive written by generate_and_record_archive is readable via get_project_archive.

    §1 cross-module: reentry/leave.py writes → project_archive table → memory/archive.py reads.
    Source ≠ sink: generate_and_record_archive (source) ≠ get_project_archive (sink).
    Discriminating: fails if archive is not persisted to the table.
    """
    store, conn = _make_store()
    room, events = _seed_room(store, conn)
    router = _mock_router(_MOCK_SUMMARY)

    archive = generate_and_record_archive(
        room.id,
        "My Room",
        events,
        room,
        start_ts=TimestampMs(1000),
        end_ts=TimestampMs(4000),
        llm_router=router,
        conn=conn,
    )

    loaded = get_project_archive(room.id, conn)
    assert loaded is not None
    assert loaded.room_id == room.id
    assert loaded.title == "My Room"
    assert loaded.duration_ms == 3000
    assert loaded.one_line_summary == "Test archive summary."
    assert loaded.spinoff_questions == ["What next?", "Any risks?"]
    assert archive.room_id == loaded.room_id


def test_generate_and_record_archive_uses_llm_output_for_semantic_fields() -> None:
    """Semantic fields come from the LLM response, not from hardcoded values.

    Discriminating: use a different mock response; assert the fields differ from
    the original _MOCK_SUMMARY defaults.
    """
    store, conn = _make_store()
    room, events = _seed_room(store, conn)
    custom_summary = json.dumps(
        {
            "one_line_summary": "Unique custom summary.",
            "spinoff_questions": ["Custom Q?"],
        }
    )
    router = _mock_router(custom_summary)

    generate_and_record_archive(
        room.id,
        "Custom Room",
        events,
        room,
        start_ts=TimestampMs(0),
        end_ts=TimestampMs(1000),
        llm_router=router,
        conn=conn,
    )

    loaded = get_project_archive(room.id, conn)
    assert loaded is not None
    assert loaded.one_line_summary == "Unique custom summary."
    assert loaded.spinoff_questions == ["Custom Q?"]


def test_generate_and_record_archive_marks_degradation_on_garbled_llm_output() -> None:
    """Garbled/non-JSON LLM output is persisted with [degraded] marker, not raw content.

    Q5 discriminating: asserts the degradation marker is present and raw garbled
    LLM text is NOT stored as one_line_summary.
    """
    store, conn = _make_store()
    room, events = _seed_room(store, conn)
    router = _mock_router("I'm sorry, I cannot generate a summary. This is not JSON.")

    generate_and_record_archive(
        room.id,
        "Degraded Room",
        events,
        room,
        start_ts=TimestampMs(0),
        end_ts=TimestampMs(1000),
        llm_router=router,
        conn=conn,
    )

    loaded = get_project_archive(room.id, conn)
    assert loaded is not None
    assert loaded.one_line_summary.startswith("[degraded]"), (
        f"Expected degradation marker '[degraded]' prefix, got: {loaded.one_line_summary!r}"
    )
    assert "sorry" not in loaded.one_line_summary.lower(), (
        "Raw LLM error text must not appear in the persisted summary"
    )
    assert loaded.spinoff_questions == []


def test_generate_and_record_archive_memory_does_not_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """memory/ does not call the LLM — generation is in reentry/, not in memory/.

    Principle 5: the archive generation happens outside memory/. After
    generate_and_record_archive persists the archive, re-reading it via
    get_project_archive does NOT trigger any LLM call.
    """
    store, conn = _make_store()
    room, events = _seed_room(store, conn)
    router = _mock_router(_MOCK_SUMMARY)

    generate_and_record_archive(
        room.id,
        "Room",
        events,
        room,
        start_ts=TimestampMs(0),
        end_ts=TimestampMs(2000),
        llm_router=router,
        conn=conn,
    )

    call_count_after_write = router.call.call_count

    # Re-reading via memory/ must NOT add more LLM calls.
    _ = get_project_archive(room.id, conn)
    assert router.call.call_count == call_count_after_write, (
        "get_project_archive must not call the LLM — generation is in reentry/"
    )
