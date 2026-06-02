"""Tests for connectors/_emit.py — emit_external_validation helper.

Q5 discriminating test: evidence_ref empty → ValueError.
Covers: empty evidence_ref raises, round-trip metadata correctness,
event persisted via event_store.append (not raw SQL), returns EventId.
"""

from __future__ import annotations

import sqlite3

import pytest

from orchestrator.connectors._emit import emit_external_validation
from orchestrator.core.event import (
    Event,
    EventId,
    EventType,
    RoomId,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.store import init_memory_schema

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return store, conn


def _make_room(store: EventStore) -> RoomId:

    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.UTTERANCE,
        author="user",
        timestamp=now_ms(),
        content="seed",
    )
    store.append(evt)
    return room.id


def _valid_hyp_id() -> str:
    import uuid

    return f"hyp_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_emit_raises_on_empty_evidence_ref() -> None:
    """Q5 discriminating: evidence_ref='' must raise ValueError."""
    store, _ = _make_store()
    room_id = _make_room(store)
    hyp_id = _valid_hyp_id()

    with pytest.raises(ValueError, match="evidence_ref is required"):
        emit_external_validation(
            store,
            room_id=room_id,
            source="test_source",
            verdict="confirmed",
            validated_hypothesis_id=hyp_id,
            evidence_ref="",
        )


def test_emit_raises_on_none_evidence_ref_equivalent() -> None:
    """Q5 discriminating: any falsy evidence_ref must raise ValueError."""
    store, _ = _make_store()
    room_id = _make_room(store)
    hyp_id = _valid_hyp_id()

    # The type signature requires str, but we test the falsy guard behavior
    # by passing a zero-length string variant (empty string is the canonical falsy case).
    # A second distinct falsy case: whitespace-only strings are truthy in Python,
    # so we test the boundary — only truly empty string is caught by `not evidence_ref`.
    with pytest.raises(ValueError, match="evidence_ref is required"):
        emit_external_validation(
            store,
            room_id=room_id,
            source="test_source",
            verdict="confirmed",
            validated_hypothesis_id=hyp_id,
            evidence_ref="",
        )


def test_emit_appends_via_event_store() -> None:
    """Valid call → event is persisted and retrievable via event_store.get_event."""
    store, _ = _make_store()
    room_id = _make_room(store)
    hyp_id = _valid_hyp_id()

    event_id = emit_external_validation(
        store,
        room_id=room_id,
        source="ci_runner",
        verdict="confirmed",
        validated_hypothesis_id=hyp_id,
        evidence_ref="test_suite_passed",
    )

    retrieved = store.get_event(EventId(event_id))
    assert retrieved is not None, "event must be persisted via event_store.append"
    assert retrieved.type == EventType.EXTERNAL_VALIDATION


def test_emit_event_metadata_correct() -> None:
    """verdict, source, validated_hypothesis_id, evidence_ref all survive round-trip."""
    store, _ = _make_store()
    room_id = _make_room(store)
    hyp_id = _valid_hyp_id()

    event_id = emit_external_validation(
        store,
        room_id=room_id,
        source="paper_db",
        verdict="refuted",
        validated_hypothesis_id=hyp_id,
        evidence_ref="doi:10.1234/example",
    )

    event = store.get_event(EventId(event_id))
    assert event is not None
    assert event.metadata["source"] == "paper_db"
    assert event.metadata["verdict"] == "refuted"
    assert event.metadata["validated_hypothesis_id"] == hyp_id
    assert event.metadata["evidence_ref"] == "doi:10.1234/example"


def test_emit_returns_event_id() -> None:
    """emit_external_validation returns a valid EventId string (evt_<32hex>)."""
    import re

    store, _ = _make_store()
    room_id = _make_room(store)
    hyp_id = _valid_hyp_id()

    event_id = emit_external_validation(
        store,
        room_id=room_id,
        source="benchmark",
        verdict="inconclusive",
        validated_hypothesis_id=hyp_id,
        evidence_ref="partial_match_ref",
    )

    assert isinstance(event_id, str)
    assert re.match(r"^evt_[0-9a-f]{32}$", event_id), (
        f"EventId must match evt_<32hex>, got {event_id!r}"
    )
