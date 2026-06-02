"""Tests for memory/validation.py — list_refuted_candidates advisory reader.

Per plan P2.6-5 B3: pure-code reader, no status mutation, fail-loud canary.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from orchestrator.core.event import (
    Event,
    EventId,
    EventType,
    RoomId,
    TimestampMs,
    generate_event_id,
    generate_room_id,
    now_ms,
    validate_metadata,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.store import init_memory_schema, record_hypothesis
from orchestrator.memory.validation import (
    list_externally_validated_candidates,
    list_refuted_candidates,
)

# ---------------------------------------------------------------------------
# Fixtures (mirror test_p2_3_e2e.py)
# ---------------------------------------------------------------------------


def _make_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return store, conn


def _make_room(store: EventStore, *, n_events: int = 2) -> tuple[Room, list[EventId]]:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    ids = []
    base = now_ms()
    for i in range(n_events):
        evt = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.UTTERANCE,
            author="user",
            timestamp=TimestampMs(base + i),
            content=f"evt {i}",
        )
        store.append(evt)
        ids.append(evt.id)
    return room, ids


def _inject_validation(
    store: EventStore,
    room_id: RoomId,
    verdict: str,
    hyp_id: str,
    *,
    source: str = "ci",
    ts_offset: int = 0,
) -> str:
    meta = validate_metadata(
        EventType.EXTERNAL_VALIDATION,
        {"source": source, "verdict": verdict, "validated_hypothesis_id": hyp_id},
    )
    evt = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.EXTERNAL_VALIDATION,
        author="system",
        timestamp=TimestampMs(now_ms() + ts_offset),
        content=f"validation: {verdict}",
        metadata=meta,
    )
    store.append(evt)
    return evt.id


# ---------------------------------------------------------------------------
# Tests for list_refuted_candidates
# ---------------------------------------------------------------------------


def test_list_refuted_candidates_returns_refuted() -> None:
    """A PENDING hypothesis with a refuted validation event appears in the result."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    hyp = record_hypothesis(
        content="refuted claim",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.7,
        conn=conn,
    )
    _inject_validation(store, room.id, "refuted", hyp.id)

    result = list_refuted_candidates(conn)
    assert len(result) == 1
    assert result[0].id == hyp.id


def test_list_refuted_candidates_excludes_confirmed() -> None:
    """A hypothesis with a confirmed verdict is NOT returned by list_refuted_candidates."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    hyp = record_hypothesis(
        content="confirmed claim",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.8,
        conn=conn,
    )
    _inject_validation(store, room.id, "confirmed", hyp.id)

    result = list_refuted_candidates(conn)
    assert result == []


def test_list_refuted_candidates_status_unchanged() -> None:
    """After calling list_refuted_candidates, the hypothesis status is still PENDING.

    Discriminating: explicitly asserts status == 'pending' to confirm no mutation.
    """
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    hyp = record_hypothesis(
        content="refuted but status stays pending",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.65,
        conn=conn,
    )
    _inject_validation(store, room.id, "refuted", hyp.id)

    result = list_refuted_candidates(conn)
    assert len(result) == 1
    # Discriminating assertion: status must remain 'pending' — reader never mutates
    assert result[0].status.value == "pending", (
        f"list_refuted_candidates must not mutate status; got {result[0].status.value!r}"
    )

    # Reload from DB to confirm no mutation persisted
    row = conn.execute("SELECT status FROM hypothesis WHERE id = ?", (hyp.id,)).fetchone()
    assert row is not None
    assert row["status"] == "pending", (
        f"DB status was mutated; expected 'pending', got {row['status']!r}"
    )


def test_list_refuted_candidates_empty_with_no_events() -> None:
    """No external_validation events at all → empty list."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    record_hypothesis(
        content="unvalidated claim",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.6,
        conn=conn,
    )

    assert list_refuted_candidates(conn) == []


def test_list_refuted_candidates_only_confirmed_not_returned() -> None:
    """All external_validation events are confirmed → refuted reader returns empty list."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=3)

    hyp_a = record_hypothesis(
        content="confirmed claim A",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.9,
        conn=conn,
    )
    hyp_b = record_hypothesis(
        content="confirmed claim B",
        room_id=room.id,
        source_event_ids=[evts[1]],
        confidence=0.85,
        conn=conn,
    )
    _inject_validation(store, room.id, "confirmed", hyp_a.id, ts_offset=1)
    _inject_validation(store, room.id, "confirmed", hyp_b.id, ts_offset=2)

    # Confirmed reader should see both; refuted reader should see none
    confirmed = list_externally_validated_candidates(conn)
    assert len(confirmed) == 2

    assert list_refuted_candidates(conn) == []


def test_list_refuted_candidates_multiple_refuted_events_deduped() -> None:
    """Two refuted events for the same hypothesis → only one result row (deduplication)."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=3)

    hyp = record_hypothesis(
        content="doubly refuted claim",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.7,
        conn=conn,
    )
    _inject_validation(store, room.id, "refuted", hyp.id, source="ci", ts_offset=1)
    _inject_validation(store, room.id, "refuted", hyp.id, source="doi-resolver", ts_offset=2)

    result = list_refuted_candidates(conn)
    assert len(result) == 1
    assert result[0].id == hyp.id


def test_list_refuted_candidates_inconclusive_not_returned() -> None:
    """An inconclusive verdict is NOT returned by list_refuted_candidates."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    hyp = record_hypothesis(
        content="inconclusive claim",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.5,
        conn=conn,
    )
    _inject_validation(store, room.id, "inconclusive", hyp.id)

    assert list_refuted_candidates(conn) == []


def test_list_refuted_candidates_raises_on_malformed_raw_insert() -> None:
    """A raw-INSERTed malformed external_validation row makes the reader RAISE (KeyError canary).

    Every sanctioned external_validation event goes through EventStore.append ->
    validate_metadata + ExternalValidationMeta extra="forbid", so a metadata shape
    missing `verdict` is unreachable via append(). The ONLY way to construct it is a
    raw INSERT bypassing EventStore.append — and per ADR-019 D2 the reader must surface
    that loudly (KeyError constitutional canary), NOT silently skip it.
    This guards the reader's direct-subscript posture against future drift back to .get()-skip.
    """
    store, conn = _make_store()
    room, _evts = _make_room(store, n_events=1)

    # Raw INSERT bypassing EventStore.append / validate_metadata: metadata lacks 'verdict'.
    conn.execute(
        "INSERT INTO events"
        " (id, parent_id, room_id, type, author, timestamp, content, metadata)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            generate_event_id(),
            None,
            room.id,
            "external_validation",
            "system",
            now_ms(),
            "malformed",
            json.dumps({"source": "ci"}),  # missing verdict
        ),
    )
    conn.commit()

    with pytest.raises(KeyError):
        list_refuted_candidates(conn)
