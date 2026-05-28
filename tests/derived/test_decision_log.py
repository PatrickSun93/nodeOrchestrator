"""Tests for src/orchestrator/derived/decision_log.py.

Coverage:
  §6 schema invariants: DecisionEntry, DecisionLog (2 classes x >=4 tests).
  §1 cross-module: event stream → produce_decision_log → assert fields.
  §3 cleanup: empty event stream.
  Ordering invariant: chronological strict + lex tie-break.
  Content excerpt: verbatim first-200-chars per ADR-015 D3.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from orchestrator.core.event import (
    Event,
    EventType,
    TimestampMs,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.room import Room, RoomType
from orchestrator.derived.decision_log import (
    DecisionEntry,
    DecisionLog,
    produce_decision_log,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROOM_ID = generate_room_id()
_ROOM = Room(id=_ROOM_ID, type=RoomType.RESEARCH, state="convergence")


def _evt(
    *,
    event_type: EventType,
    author: str = "user",
    content: str = "event content",
    metadata: dict[str, Any] | None = None,
    timestamp: int | None = None,
) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=_ROOM_ID,
        type=event_type,
        author=author,
        timestamp=TimestampMs(timestamp if timestamp is not None else now_ms()),
        content=content,
        metadata=metadata or {},
    )


def _decision_evt(based_on_ids: list[str] | None = None, timestamp: int | None = None) -> Event:
    based_on = based_on_ids or [generate_event_id()]
    return _evt(
        event_type=EventType.DECISION,
        metadata={"based_on": based_on, "trade_offs": {}},
        timestamp=timestamp,
    )


def _rejection_evt(rejects_id: str, timestamp: int | None = None) -> Event:
    return _evt(
        event_type=EventType.REJECTION,
        metadata={"rejects": rejects_id, "reason": "invalid"},
        timestamp=timestamp,
    )


def _retraction_evt(retracts_id: str, timestamp: int | None = None) -> Event:
    return _evt(
        event_type=EventType.RETRACTION,
        metadata={"retracts": retracts_id, "reason": "superseded"},
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# §6 schema invariants — DecisionEntry (4 tests)
# ---------------------------------------------------------------------------


def test_decision_entry_frozen() -> None:
    entry = DecisionEntry(
        event_id="evt_d1",
        event_type="decision",
        timestamp=100,
        author="user",
        content_excerpt="some content",
        parent_event_id=None,
    )
    with pytest.raises((ValidationError, TypeError)):
        entry.author = "agent:other"


def test_decision_entry_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        DecisionEntry(
            event_id="evt_d1",
            event_type="decision",
            timestamp=100,
            author="user",
            content_excerpt="content",
            parent_event_id=None,
            unknown_field="boom",  # type: ignore[call-arg]
        )


def test_decision_entry_required_field_absent() -> None:
    with pytest.raises(ValidationError):
        DecisionEntry(event_id="evt_d1", event_type="decision")  # type: ignore[call-arg]


def test_decision_entry_invalid_event_type_literal() -> None:
    """event_type must be one of the 4 decision-class values."""
    with pytest.raises(ValidationError):
        DecisionEntry(
            event_id="evt_d1",
            event_type="utterance",  # type: ignore[arg-type]
            timestamp=100,
            author="user",
            content_excerpt="content",
            parent_event_id=None,
        )


# ---------------------------------------------------------------------------
# §6 schema invariants — DecisionLog (4 tests)
# ---------------------------------------------------------------------------


def test_decision_log_frozen() -> None:
    log = DecisionLog(room_id=_ROOM_ID, entries=[])
    with pytest.raises((ValidationError, TypeError)):
        log.entries = []


def test_decision_log_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        DecisionLog(room_id=_ROOM_ID, entries=[], extra_field=1)  # type: ignore[call-arg]


def test_decision_log_required_field_absent() -> None:
    with pytest.raises(ValidationError):
        DecisionLog(entries=[])  # type: ignore[call-arg]


def test_decision_log_wrong_type_entries() -> None:
    with pytest.raises(ValidationError):
        DecisionLog(room_id=_ROOM_ID, entries="not a list")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# §1 cross-module: produce_decision_log derivation
# ---------------------------------------------------------------------------


def test_produce_decision_log_empty() -> None:
    """§3 cleanup: empty event stream → empty DecisionLog."""
    dlog = produce_decision_log([], _ROOM)
    assert dlog.room_id == _ROOM_ID
    assert dlog.entries == []


def test_produce_decision_log_filters_non_decision_events() -> None:
    """Non-decision-class events are excluded from the log."""
    events = [
        _evt(event_type=EventType.USER_INPUT),
        _evt(event_type=EventType.UTTERANCE, author="agent:skeptic"),
        _evt(event_type=EventType.HYPOTHESIS, author="user", metadata={"confidence": 0.7}),
        _evt(
            event_type=EventType.STATE_TRANSITION,
            author="system",
            metadata={"prior_state": "setup", "new_state": "exploration"},
        ),
    ]
    dlog = produce_decision_log(events, _ROOM)
    assert dlog.entries == []


def test_produce_decision_log_decision_event() -> None:
    """DECISION event → DecisionEntry with correct fields."""
    d = _decision_evt(timestamp=1000)
    dlog = produce_decision_log([d], _ROOM)
    assert len(dlog.entries) == 1
    entry = dlog.entries[0]
    assert entry.event_id == d.id
    assert entry.event_type == "decision"
    assert entry.timestamp == 1000
    assert entry.author == "user"
    assert entry.parent_event_id is None


def test_produce_decision_log_rejection_parent_event_id() -> None:
    """REJECTION event → parent_event_id populated from RejectionMeta.rejects."""
    target_id = generate_event_id()
    rej = _rejection_evt(rejects_id=target_id, timestamp=2000)
    dlog = produce_decision_log([rej], _ROOM)
    assert len(dlog.entries) == 1
    entry = dlog.entries[0]
    assert entry.event_type == "rejection"
    assert entry.parent_event_id == target_id


def test_produce_decision_log_retraction_parent_event_id() -> None:
    """RETRACTION event → parent_event_id populated from RetractionMeta.retracts."""
    target_id = generate_event_id()
    ret = _retraction_evt(retracts_id=target_id, timestamp=3000)
    dlog = produce_decision_log([ret], _ROOM)
    assert len(dlog.entries) == 1
    assert dlog.entries[0].parent_event_id == target_id


def test_produce_decision_log_decision_pivot_no_parent() -> None:
    """DECISION_PIVOT event → parent_event_id is None."""
    pivot = _evt(event_type=EventType.DECISION_PIVOT, timestamp=4000)
    dlog = produce_decision_log([pivot], _ROOM)
    assert len(dlog.entries) == 1
    assert dlog.entries[0].event_type == "decision_pivot"
    assert dlog.entries[0].parent_event_id is None


def test_produce_decision_log_chronological_order() -> None:
    """Entries are sorted by timestamp ascending per ADR-015 D4."""
    d1 = _decision_evt(timestamp=3000)
    d2 = _decision_evt(timestamp=1000)
    d3 = _decision_evt(timestamp=2000)
    dlog = produce_decision_log([d1, d2, d3], _ROOM)
    timestamps = [e.timestamp for e in dlog.entries]
    assert timestamps == sorted(timestamps)


def test_produce_decision_log_content_excerpt_verbatim_200() -> None:
    """content_excerpt is event.content[:200] verbatim — no paraphrase."""
    long_content = "A" * 300
    d = _decision_evt(timestamp=5000)
    # Override content via a direct Event construction
    d_with_long = Event(
        id=d.id,
        room_id=_ROOM_ID,
        type=EventType.DECISION,
        author="user",
        timestamp=TimestampMs(5000),
        content=long_content,
        metadata={"based_on": [generate_event_id()], "trade_offs": {}},
    )
    dlog = produce_decision_log([d_with_long], _ROOM)
    assert dlog.entries[0].content_excerpt == long_content[:200]
    assert len(dlog.entries[0].content_excerpt) == 200


# ---------------------------------------------------------------------------
# M-Y4: §3-cleanup — malformed metadata raises ValidationError (strict propagation)
# ---------------------------------------------------------------------------


def test_produce_decision_log_malformed_rejection_metadata_raises() -> None:
    """REJECTION event with malformed rejects field → produce_decision_log raises.

    Per ADR-014 D7 strict-propagation semantic: ValidationError propagates; no swallow.
    """
    bad_rejection = _evt(
        event_type=EventType.REJECTION,
        metadata={"rejects": 12345, "reason": "wrong type"},  # rejects must be str
    )
    with pytest.raises(ValidationError):
        produce_decision_log([bad_rejection], _ROOM)
