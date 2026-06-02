"""Tests for connectors/dataset_check.py — deterministic dataset connector.

Covers: confirmed match, inconclusive (no match), determinism,
and verifying connector calls emit_external_validation (not constructing
ExternalValidationMeta directly).
"""

from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import patch

from orchestrator.connectors.dataset_check import check_hypothesis_against_dataset
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
    return f"hyp_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dataset_check_confirmed() -> None:
    """Hypothesis matching a dataset key → returns EventId with verdict=confirmed."""
    store, _ = _make_store()
    room_id = _make_room(store)
    hyp_id = _valid_hyp_id()

    dataset = {
        "gravity": "objects accelerate at 9.8 m/s^2 near Earth surface",
        "entropy": "disorder tends to increase in closed systems",
    }
    hypothesis = "Gravity causes objects to fall at constant acceleration"

    result = check_hypothesis_against_dataset(
        hypothesis,
        dataset,
        event_store=store,
        room_id=room_id,
        validated_hypothesis_id=hyp_id,
    )

    assert result is not None, "should return EventId on confirmed match"
    event = store.get_event(EventId(result))
    assert event is not None
    assert event.metadata["verdict"] == "confirmed"
    assert event.metadata["evidence_ref"] == "gravity"


def test_dataset_check_inconclusive() -> None:
    """Hypothesis not matching any dataset key → returns None (no event written)."""
    store, _ = _make_store()
    room_id = _make_room(store)
    hyp_id = _valid_hyp_id()

    dataset = {
        "photosynthesis": "plants convert sunlight to glucose",
        "mitosis": "cells divide into two identical daughter cells",
    }
    hypothesis = "Black holes warp spacetime near the event horizon"

    result = check_hypothesis_against_dataset(
        hypothesis,
        dataset,
        event_store=store,
        room_id=room_id,
        validated_hypothesis_id=hyp_id,
    )

    assert result is None, "should return None when no dataset key matches"


def test_dataset_check_deterministic() -> None:
    """Same hypothesis + dataset → same verdict and evidence_ref twice."""
    store, _ = _make_store()
    room_id = _make_room(store)

    dataset = {
        "quantum": "particles exhibit wave-particle duality",
        "relativity": "spacetime curvature causes gravity",
    }
    hypothesis = "Quantum mechanics describes subatomic particle behavior"

    hyp_id_1 = _valid_hyp_id()
    hyp_id_2 = _valid_hyp_id()

    result_1 = check_hypothesis_against_dataset(
        hypothesis,
        dataset,
        event_store=store,
        room_id=room_id,
        validated_hypothesis_id=hyp_id_1,
    )
    result_2 = check_hypothesis_against_dataset(
        hypothesis,
        dataset,
        event_store=store,
        room_id=room_id,
        validated_hypothesis_id=hyp_id_2,
    )

    assert result_1 is not None and result_2 is not None

    event_1 = store.get_event(EventId(result_1))
    event_2 = store.get_event(EventId(result_2))
    assert event_1 is not None and event_2 is not None

    # Same verdict and same evidence_ref (deterministic)
    assert event_1.metadata["verdict"] == event_2.metadata["verdict"]
    assert event_1.metadata["evidence_ref"] == event_2.metadata["evidence_ref"]


def test_dataset_check_calls_emit_helper() -> None:
    """dataset_check calls emit_external_validation, not ExternalValidationMeta directly."""
    store, _ = _make_store()
    room_id = _make_room(store)
    hyp_id = _valid_hyp_id()

    dataset = {"photon": "massless particle of light"}
    hypothesis = "A photon travels at the speed of light"

    with patch("orchestrator.connectors.dataset_check.emit_external_validation") as mock_emit:
        mock_emit.return_value = EventId(f"evt_{uuid.uuid4().hex}")

        check_hypothesis_against_dataset(
            hypothesis,
            dataset,
            event_store=store,
            room_id=room_id,
            validated_hypothesis_id=hyp_id,
        )

    mock_emit.assert_called_once()
    call_kwargs = mock_emit.call_args.kwargs
    assert call_kwargs["verdict"] == "confirmed"
    assert call_kwargs["evidence_ref"] == "photon"
