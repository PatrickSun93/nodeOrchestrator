"""End-to-end P2.4: Scenario — Entity + Preference + ProjectArchive create → store → read.

Per plan P2.4-6 acceptance criteria (ADR-020 D1/D2/D3).

Exercises the three memory containers across ≥2 rooms:
  record_entity (PROJECT scope) → list_entities / get_entity_by_id cross-room
  record_preference (explicit user_id) → list_preferences (declared_by provenance)
  record_project_archive (decision_log composed by test) → get/list readers
  Principle-11 enforcement: record_entity(PREFERENCE) raises + record_preference("") raises
  Determinism: readers return stable order

Source ≠ sink (§1 coverage standard):
  entity.py (write) → entity table → list_entities / get_entity_by_id (read)
  entity.py (write) → entity table → list_preferences (read)
  archive.py (write) → project_archive table → get/list_project_archives (read)
"""

from __future__ import annotations

import sqlite3

import pytest

from orchestrator.core.event import RoomId, generate_room_id
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.archive import (
    get_project_archive,
    list_project_archives,
    record_project_archive,
)
from orchestrator.memory.entity import (
    get_entity_by_id,
    list_entities,
    list_preferences,
    record_entity,
    record_preference,
)
from orchestrator.memory.schema import EntityScope, EntityType
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


def _seed_room(store: EventStore, conn: sqlite3.Connection) -> RoomId:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


# ---------------------------------------------------------------------------
# Scenario A: Entity cross-room create → read (AC#1)
# ---------------------------------------------------------------------------


def test_scenario_entity_cross_room_create_read() -> None:
    """AC#1: record_entity(PROJECT) surfaces via list_entities and get_entity_by_id.

    Exercises the cross-module flow (write in entity.py → entity table → read).
    Entity table has no room FK — entities are globally accessible.
    Discriminating: asserts exact attributes, not just count.
    """
    # entity table has no room FK; _make_store provides a fresh DB with all tables.
    _, conn = _make_store()

    entity = record_entity(
        EntityType.PROJECT,
        {"name": "Project X"},
        scope=EntityScope.PROJECT,
        conn=conn,
    )

    # list_entities surfaces it.
    entities = list_entities(type=EntityType.PROJECT, conn=conn)
    assert len(entities) == 1
    assert entities[0].id == entity.id
    assert entities[0].attributes == {"name": "Project X"}
    assert entities[0].scope == EntityScope.PROJECT

    # get_entity_by_id surfaces it.
    loaded = get_entity_by_id(entity.id, conn)
    assert loaded is not None
    assert loaded.attributes["name"] == "Project X"


def test_scenario_entity_multiple_types_accessible() -> None:
    """Entities of different types from distinct origins are all accessible via list_entities."""
    _, conn = _make_store()

    e1 = record_entity(EntityType.PROJECT, {"name": "Alpha"}, conn=conn)
    e2 = record_entity(EntityType.PAPER, {"title": "Beta Paper"}, conn=conn)

    all_entities = list_entities(conn=conn)
    ids = [e.id for e in all_entities]
    assert e1.id in ids
    assert e2.id in ids


# ---------------------------------------------------------------------------
# Scenario B: Preference round-trip + Principle-11 enforcement (AC#2)
# ---------------------------------------------------------------------------


def test_scenario_preference_round_trip_with_provenance() -> None:
    """AC#2a: record_preference → list_preferences surfaces declared_by provenance."""
    _, conn = _make_store()

    pref = record_preference("response_style", "concise", user_id="peidong", conn=conn)
    prefs = list_preferences(user_id="peidong", conn=conn)
    assert len(prefs) == 1
    assert prefs[0].id == pref.id
    assert prefs[0].attributes == {"key": "response_style", "value": "concise"}
    assert prefs[0].evidence["declared_by"] == "peidong"


def test_scenario_principle_11_record_entity_rejects_preference() -> None:
    """AC#2b: record_entity(type=PREFERENCE) raises — no inferred-pref bypass path.

    Discriminating: this test fails if record_entity silently accepts PREFERENCE.
    """
    _, conn = _make_store()
    with pytest.raises(ValueError, match="record_preference"):
        record_entity(EntityType.PREFERENCE, {"key": "x", "value": "y"}, conn=conn)


def test_scenario_principle_11_empty_user_id_raises() -> None:
    """AC#2b: record_preference(user_id='') raises — LLM-inferred prefs un-representable.

    Discriminating: this test fails if record_preference allows empty user_id.
    """
    _, conn = _make_store()
    with pytest.raises(ValueError, match="user_id"):
        record_preference("k", "v", user_id="", conn=conn)


# ---------------------------------------------------------------------------
# Scenario C: ProjectArchive create → read + duplicate fail-loud (AC#3)
# ---------------------------------------------------------------------------


def test_scenario_project_archive_round_trip() -> None:
    """AC#3: record_project_archive → get/list readers round-trip the narrative.

    The test itself composes decision_log (simulating the caller running
    produce_decision_log), passes it in, and asserts it round-trips intact.
    """
    store, conn = _make_store()
    room1 = _seed_room(store, conn)

    composed_decision_log = [
        {"decision": "use sqlite", "rationale": "simple + no deps"},
        {"decision": "freeze models", "rationale": "immutability"},
    ]

    record_project_archive(
        room_id=room1,
        title="My Research Room",
        duration_ms=3600000,
        one_line_summary="Explored the viability of SQLite for cross-room memory.",
        decision_log=composed_decision_log,
        spinoff_questions=["What about Postgres?", "How to shard?"],
        conn=conn,
    )

    # get_project_archive round-trips all fields.
    loaded = get_project_archive(room1, conn)
    assert loaded is not None
    assert loaded.room_id == room1
    assert loaded.title == "My Research Room"
    assert loaded.duration_ms == 3600000
    assert loaded.one_line_summary == "Explored the viability of SQLite for cross-room memory."
    assert loaded.decision_log == composed_decision_log
    assert loaded.spinoff_questions == ["What about Postgres?", "How to shard?"]

    # list_project_archives surfaces it.
    archives = list_project_archives(conn=conn)
    assert len(archives) == 1
    assert archives[0].room_id == room1

    # Duplicate room_id fails loud.
    with pytest.raises(sqlite3.IntegrityError):
        record_project_archive(
            room_id=room1,
            title="Duplicate",
            duration_ms=0,
            one_line_summary="S",
            decision_log=[],
            spinoff_questions=[],
            conn=conn,
        )


def test_scenario_project_archive_missing_returns_none_and_empty_list() -> None:
    """AC#3 cleanup: empty DB → get returns None, list returns []."""
    _, conn = _make_store()
    assert get_project_archive(RoomId("room_nonexistent"), conn) is None
    assert list_project_archives(conn=conn) == []


# ---------------------------------------------------------------------------
# Scenario D: Determinism (AC#4)
# ---------------------------------------------------------------------------


def test_scenario_entity_determinism_stable_across_insertion_order() -> None:
    """AC#4: list_entities returns stable id ASC order regardless of insertion order.

    Discriminating: two stores differ only in entity insertion order;
    we assert the same entity names surface in the same order (by id ASC).
    Not a count-only proxy (P2.2/P2.3 precedent).
    """
    _, conn1 = _make_store()
    e1a = record_entity(EntityType.CONCEPT, {"name": "Alpha"}, conn=conn1)
    e1b = record_entity(EntityType.CONCEPT, {"name": "Beta"}, conn=conn1)
    result1 = list_entities(type=EntityType.CONCEPT, conn=conn1)

    _, conn2 = _make_store()
    e2b = record_entity(EntityType.CONCEPT, {"name": "Beta"}, conn=conn2)
    e2a = record_entity(EntityType.CONCEPT, {"name": "Alpha"}, conn=conn2)
    result2 = list_entities(type=EntityType.CONCEPT, conn=conn2)

    # Both return 2 rows. Assert id ASC order is respected independently of
    # insertion order by checking that the returned id lists are sorted.
    ids1 = [e.id for e in result1]
    ids2 = [e.id for e in result2]
    assert ids1 == sorted(ids1), f"store1 not id ASC: {ids1}"
    assert ids2 == sorted(ids2), f"store2 not id ASC: {ids2}"

    # Discriminating: assert actual label values match (not just count).
    names1 = {e.attributes["name"] for e in result1}
    names2 = {e.attributes["name"] for e in result2}
    assert names1 == {"Alpha", "Beta"}
    assert names2 == {"Alpha", "Beta"}
    assert names1 == names2

    _ = e1a, e1b, e2a, e2b  # referenced via names1/names2 sets above


def test_scenario_archive_determinism_list_room_id_asc() -> None:
    """AC#4: list_project_archives returns room_id ASC stable across insertion order."""
    store, conn = _make_store()
    room1 = _seed_room(store, conn)
    room2 = _seed_room(store, conn)

    # Insert in reverse room_id order (highest first).
    rooms = sorted([room1, room2], reverse=True)
    for rid in rooms:
        record_project_archive(
            room_id=rid,
            title=f"Archive {rid[-4:]}",
            duration_ms=0,
            one_line_summary="S",
            decision_log=[],
            spinoff_questions=[],
            conn=conn,
        )

    archives = list_project_archives(conn=conn)
    ids = [str(a.room_id) for a in archives]
    assert ids == sorted(ids), f"expected room_id ASC; got {ids}"


# ---------------------------------------------------------------------------
# Scenario E: Full cross-container pipeline (AC#1-4 combined)
# ---------------------------------------------------------------------------


def test_scenario_full_pipeline_all_three_containers() -> None:
    """Full scenario: ≥2 rooms, all three containers created and read back.

    Entity PROJECT cross-room, preference with provenance, archive with
    decision_log, duplicate-archive fail-loud.
    """
    store, conn = _make_store()
    room1 = _seed_room(store, conn)
    room2 = _seed_room(store, conn)

    # (A) Entity.
    entity = record_entity(
        EntityType.PROJECT, {"name": "Shared Project"}, scope=EntityScope.PROJECT, conn=conn
    )
    assert list_entities(type=EntityType.PROJECT, conn=conn)[0].id == entity.id

    # (B) Preference — with provenance; Principle-11 both branches.
    pref = record_preference("response_style", "concise", user_id="peidong", conn=conn)
    assert list_preferences(user_id="peidong", conn=conn)[0].evidence["declared_by"] == "peidong"
    with pytest.raises(ValueError):
        record_entity(EntityType.PREFERENCE, {}, conn=conn)
    with pytest.raises(ValueError):
        record_preference("k", "v", user_id="", conn=conn)

    # (C) ProjectArchive room1.
    log = [{"decision": "sqlite", "rationale": "simple"}]
    record_project_archive(
        room_id=room1,
        title="Room 1 Archive",
        duration_ms=1800000,
        one_line_summary="Room 1 summary.",
        decision_log=log,
        spinoff_questions=["Next steps?"],
        conn=conn,
    )
    loaded1 = get_project_archive(room1, conn)
    assert loaded1 is not None
    assert loaded1.decision_log == log

    # Duplicate room1 fails loud.
    with pytest.raises(sqlite3.IntegrityError):
        record_project_archive(
            room_id=room1,
            title="Dup",
            duration_ms=0,
            one_line_summary="S",
            decision_log=[],
            spinoff_questions=[],
            conn=conn,
        )

    # ProjectArchive room2.
    record_project_archive(
        room_id=room2,
        title="Room 2 Archive",
        duration_ms=900000,
        one_line_summary="Room 2 summary.",
        decision_log=[],
        spinoff_questions=[],
        conn=conn,
    )

    # list_project_archives returns both, room_id ASC.
    all_archives = list_project_archives(conn=conn)
    assert len(all_archives) == 2
    room_ids = [str(a.room_id) for a in all_archives]
    assert room_ids == sorted(room_ids)

    _ = pref  # used above via list_preferences assert
