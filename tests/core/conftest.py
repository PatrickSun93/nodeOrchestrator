"""Shared fixtures for tests/core/.

Two fixtures are provided:

* ``in_memory_event_store`` — a fresh ``EventStore`` on an in-memory
  SQLite DB with the schema initialized. Use this for tests that need
  to build their own state.

* ``populated_event_store`` — an ``EventStore`` populated with a
  standard 8-node event tree. Use this for tests that need realistic
  multi-event state without re-deriving the whole tree.

Tests should NOT inline EventStore setup. Discipline starts at the
foundation.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import TypedDict

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
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType


class FixtureIds(TypedDict):
    """Named ids for the populated fixture's standard event tree."""

    room: RoomId
    user_input: EventId
    utterance: EventId
    tool_call: EventId
    tool_result: EventId
    hypothesis: EventId
    decision: EventId
    rejection: EventId
    retraction: EventId


PopulatedFixture = tuple[EventStore, FixtureIds]


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A fresh in-memory sqlite3 connection. Closed after the test."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def in_memory_event_store(conn: sqlite3.Connection) -> EventStore:
    """A fresh ``EventStore`` on an in-memory DB with schema initialized."""
    store = EventStore(conn)
    store.init_schema()
    return store


@pytest.fixture
def populated_event_store(in_memory_event_store: EventStore) -> PopulatedFixture:
    """Standard 8-node event tree:

    .. code-block:: text

       1. user_input         (author=user)
          └─ 2. utterance    (author=agent:operator)
              └─ 3. tool_call    (author=agent:operator, call_id=c1)
                  └─ 4. tool_result  (author=system, call_id=c1, success)
                      └─ 5. hypothesis  (author=agent:operator, conf=0.7)
                          └─ 6. decision    (author=agent:operator,
                                             based_on=[hypothesis])
                              ├─ 7. rejection   (author=agent:skeptic,
                              │                  rejects=decision)
                              └─ 8. retraction  (author=user,
                                                 retracts=decision)

    Coverage:

    * 4 distinct authors (user, agent:operator, agent:skeptic, system)
    * All 6 typed metadata schemas
      (hypothesis, decision, rejection, retraction, tool_call, tool_result)
    * All 4 structural relation types
      (replies_to, rejects, retracts, based_on)
    * Fork at decision (two children: rejection + retraction)

    Returns:
        ``(store, ids)`` where ``ids`` is a TypedDict with named keys
        for each event.
    """
    store = in_memory_event_store

    # Deterministic timestamps (avoid same-millisecond collisions).
    base = now_ms()

    def ts(offset: int) -> TimestampMs:
        return TimestampMs(base + offset)

    # Room.
    room = Room(
        id=generate_room_id(),
        type=RoomType.RESEARCH,
        created_at=ts(0),
    )
    store.append_room(room)

    # 1. user_input — the question.
    e1 = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.USER_INPUT,
        author="user",
        timestamp=ts(1),
        content="How should we structure the X module?",
    )
    store.append(e1)

    # 2. utterance — operator acknowledges and plans next step.
    e2 = Event(
        id=generate_event_id(),
        parent_id=e1.id,
        room_id=room.id,
        type=EventType.UTTERANCE,
        author="agent:operator",
        timestamp=ts(2),
        content="Let me look at how similar modules are structured.",
    )
    store.append(e2)

    # 3. tool_call — operator searches.
    e3 = Event(
        id=generate_event_id(),
        parent_id=e2.id,
        room_id=room.id,
        type=EventType.TOOL_CALL,
        author="agent:operator",
        timestamp=ts(3),
        content="search_text('module structure')",
        metadata={
            "tool_name": "search_text",
            "call_id": "c1",
            "params": {"query": "module structure"},
        },
    )
    store.append(e3)

    # 4. tool_result — system reports.
    e4 = Event(
        id=generate_event_id(),
        parent_id=e3.id,
        room_id=room.id,
        type=EventType.TOOL_RESULT,
        author="system",
        timestamp=ts(4),
        content="Found 3 similar modules using the layered pattern.",
        metadata={
            "call_id": "c1",
            "success": True,
            "output_truncated_at": None,
            "error_class": None,
        },
    )
    store.append(e4)

    # 5. hypothesis — operator forms a claim with confidence.
    e5 = Event(
        id=generate_event_id(),
        parent_id=e4.id,
        room_id=room.id,
        type=EventType.HYPOTHESIS,
        author="agent:operator",
        timestamp=ts(5),
        content="Layered pattern fits X because of dependency direction.",
        metadata={"confidence": 0.7, "based_on": []},
    )
    store.append(e5)

    # 6. decision — operator commits, citing the hypothesis.
    e6 = Event(
        id=generate_event_id(),
        parent_id=e5.id,
        room_id=room.id,
        type=EventType.DECISION,
        author="agent:operator",
        timestamp=ts(6),
        content="We will adopt the layered pattern for X.",
        metadata={
            "based_on": [e5.id],
            "trade_offs": {"complexity": "moderate", "testability": "high"},
        },
    )
    store.append(e6)

    # 7. rejection — skeptic rejects the decision (sibling fork).
    e7 = Event(
        id=generate_event_id(),
        parent_id=e6.id,
        room_id=room.id,
        type=EventType.REJECTION,
        author="agent:skeptic",
        timestamp=ts(7),
        content="Layered pattern hides the cyclic dependency in submodule Y.",
        metadata={"rejects": e6.id, "reason": "cyclic dependency in Y"},
    )
    store.append(e7)

    # 8. retraction — user withdraws the decision (sibling of rejection).
    e8 = Event(
        id=generate_event_id(),
        parent_id=e6.id,
        room_id=room.id,
        type=EventType.RETRACTION,
        author="user",
        timestamp=ts(8),
        content="Skeptic is right. Withdrawing.",
        metadata={"retracts": e6.id, "reason": "skeptic's concern is valid"},
    )
    store.append(e8)

    ids: FixtureIds = {
        "room": room.id,
        "user_input": e1.id,
        "utterance": e2.id,
        "tool_call": e3.id,
        "tool_result": e4.id,
        "hypothesis": e5.id,
        "decision": e6.id,
        "rejection": e7.id,
        "retraction": e8.id,
    }
    return (store, ids)
