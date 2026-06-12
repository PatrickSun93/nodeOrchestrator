"""Tests for memory/entity.py — record_entity, get_entity_by_id, list_entities,
record_preference, list_preferences.

Per plan P2.4-3/-4 acceptance criteria and ADR-020 D1/D2.

Coverage standard:
  §1: entity source in entity.py, reader cross-module (full e2e in test_p2_4_e2e.py).
  §5: N/A (no list/sequence field validators on the entity API itself).
  §6: no new models in this file (models in test_schema.py).
"""

from __future__ import annotations

import sqlite3

import pytest

from orchestrator.core.event import TimestampMs, generate_room_id, now_ms
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
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


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    # seed a room so FK constraints on event tables are satisfied
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    init_memory_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# record_entity — happy path + append-only contract
# ---------------------------------------------------------------------------


class TestRecordEntity:
    def test_happy_path_returns_entity(self) -> None:
        conn = _make_conn()
        e = record_entity(EntityType.PROJECT, {"name": "Project X"}, conn=conn)
        assert e.type == EntityType.PROJECT
        assert e.attributes == {"name": "Project X"}
        assert e.id.startswith("ent_")
        assert e.scope == EntityScope.PERSONAL

    def test_row_persisted(self) -> None:
        conn = _make_conn()
        e = record_entity(EntityType.CONCEPT, {"label": "SQLite"}, conn=conn)
        loaded = get_entity_by_id(e.id, conn)
        assert loaded is not None
        assert loaded.id == e.id
        assert loaded.type == EntityType.CONCEPT
        assert loaded.attributes == {"label": "SQLite"}

    def test_scope_stored_and_retrieved(self) -> None:
        conn = _make_conn()
        e = record_entity(EntityType.PERSON, {"name": "Alice"}, scope=EntityScope.GLOBAL, conn=conn)
        assert e.scope == EntityScope.GLOBAL
        loaded = get_entity_by_id(e.id, conn)
        assert loaded is not None
        assert loaded.scope == EntityScope.GLOBAL

    def test_evidence_stored_and_retrieved(self) -> None:
        conn = _make_conn()
        e = record_entity(
            EntityType.PROJECT,
            {"name": "X"},
            evidence={"source": "manual"},
            conn=conn,
        )
        assert e.evidence == {"source": "manual"}
        loaded = get_entity_by_id(e.id, conn)
        assert loaded is not None
        assert loaded.evidence == {"source": "manual"}

    def test_rejects_preference_type(self) -> None:
        """record_entity raises ValueError for type=PREFERENCE — Principle-11 bypass guard."""
        conn = _make_conn()
        with pytest.raises(ValueError, match="record_preference"):
            record_entity(EntityType.PREFERENCE, {"key": "x", "value": "y"}, conn=conn)

    def test_append_only_duplicate_creates_two_rows(self) -> None:
        """Second record_entity with identical data yields two distinct rows (Y2 → alpha).

        Discriminating: if record_entity silently deduped, list_entities would return 1.
        We seed the duplicate, then assert count==2 — this test fails if record_entity
        wrongly acts like an upsert.
        """
        conn = _make_conn()
        ts = TimestampMs(now_ms())
        attrs = {"name": "Project Alpha"}
        e1 = record_entity(EntityType.PROJECT, attrs, conn=conn, now=ts)
        e2 = record_entity(EntityType.PROJECT, attrs, conn=conn, now=ts)
        # Two distinct entity IDs.
        assert e1.id != e2.id
        # list_entities surfaces both rows.
        entities = list_entities(type=EntityType.PROJECT, conn=conn)
        assert len(entities) == 2, f"expected 2 rows (append-only); got {len(entities)}"

    def test_now_override(self) -> None:
        conn = _make_conn()
        ts = TimestampMs(1_700_000_000_000)
        e = record_entity(EntityType.PAPER, {}, conn=conn, now=ts)
        assert e.created_at == ts
        loaded = get_entity_by_id(e.id, conn)
        assert loaded is not None
        assert loaded.created_at == ts


# ---------------------------------------------------------------------------
# get_entity_by_id
# ---------------------------------------------------------------------------


class TestGetEntityById:
    def test_missing_returns_none(self) -> None:
        conn = _make_conn()
        assert get_entity_by_id("ent_" + "0" * 32, conn) is None  # type: ignore[arg-type]

    def test_round_trip_attributes(self) -> None:
        conn = _make_conn()
        e = record_entity(EntityType.PERSON, {"name": "Bob", "age": 30}, conn=conn)
        loaded = get_entity_by_id(e.id, conn)
        assert loaded is not None
        assert loaded.attributes == {"name": "Bob", "age": 30}


# ---------------------------------------------------------------------------
# list_entities
# ---------------------------------------------------------------------------


class TestListEntities:
    def test_empty_db_returns_empty(self) -> None:
        conn = _make_conn()
        assert list_entities(conn=conn) == []

    def test_no_filter_returns_all(self) -> None:
        conn = _make_conn()
        record_entity(EntityType.PROJECT, {}, conn=conn)
        record_entity(EntityType.CONCEPT, {}, conn=conn)
        assert len(list_entities(conn=conn)) == 2

    def test_type_filter(self) -> None:
        conn = _make_conn()
        record_entity(EntityType.PROJECT, {"name": "P"}, conn=conn)
        record_entity(EntityType.CONCEPT, {"name": "C"}, conn=conn)
        projects = list_entities(type=EntityType.PROJECT, conn=conn)
        assert len(projects) == 1
        assert projects[0].type == EntityType.PROJECT

    def test_scope_filter(self) -> None:
        conn = _make_conn()
        record_entity(EntityType.PROJECT, {}, scope=EntityScope.GLOBAL, conn=conn)
        record_entity(EntityType.PROJECT, {}, scope=EntityScope.PERSONAL, conn=conn)
        global_only = list_entities(scope=EntityScope.GLOBAL, conn=conn)
        assert len(global_only) == 1
        assert global_only[0].scope == EntityScope.GLOBAL

    def test_type_and_scope_filter(self) -> None:
        conn = _make_conn()
        record_entity(EntityType.PROJECT, {}, scope=EntityScope.GLOBAL, conn=conn)
        record_entity(EntityType.CONCEPT, {}, scope=EntityScope.GLOBAL, conn=conn)
        record_entity(EntityType.PROJECT, {}, scope=EntityScope.PERSONAL, conn=conn)
        result = list_entities(type=EntityType.PROJECT, scope=EntityScope.GLOBAL, conn=conn)
        assert len(result) == 1
        assert result[0].type == EntityType.PROJECT
        assert result[0].scope == EntityScope.GLOBAL

    def test_deterministic_id_asc_order(self) -> None:
        """list_entities returns rows in id ASC order regardless of insertion order."""
        conn = _make_conn()
        ts = TimestampMs(now_ms())
        e1 = record_entity(EntityType.PROJECT, {"n": "A"}, conn=conn, now=ts)
        e2 = record_entity(EntityType.PROJECT, {"n": "B"}, conn=conn, now=ts)
        entities = list_entities(type=EntityType.PROJECT, conn=conn)
        ids = [e.id for e in entities]
        # Assert the returned order matches lexicographic id ASC.
        assert ids == sorted(ids), f"expected id ASC; got {ids}"
        assert set(ids) == {e1.id, e2.id}


# ---------------------------------------------------------------------------
# record_preference — upsert contract (Y2 → alpha)
# ---------------------------------------------------------------------------


class TestRecordPreference:
    def test_happy_path_returns_entity(self) -> None:
        conn = _make_conn()
        pref = record_preference("response_style", "concise", user_id="peidong", conn=conn)
        assert pref.type == EntityType.PREFERENCE
        assert pref.attributes == {"key": "response_style", "value": "concise"}
        assert pref.evidence == {"declared_by": "peidong"}

    def test_empty_user_id_raises(self) -> None:
        """record_preference with empty user_id raises ValueError — Principle-11 enforcement."""
        conn = _make_conn()
        with pytest.raises(ValueError, match="user_id"):
            record_preference("k", "v", user_id="", conn=conn)

    def test_row_persisted_and_readable(self) -> None:
        conn = _make_conn()
        pref = record_preference("lang", "en", user_id="alice", conn=conn)
        loaded = get_entity_by_id(pref.id, conn)
        assert loaded is not None
        assert loaded.attributes["key"] == "lang"
        assert loaded.attributes["value"] == "en"
        assert loaded.evidence["declared_by"] == "alice"

    def test_upsert_same_key_yields_one_row(self) -> None:
        """Second record_preference(same user, key) updates in place → one row (Y2 → alpha).

        Discriminating: if record_preference were append-only, list_preferences
        would return 2 rows. We assert count==1 and the latest value — this test
        fails if the upsert is wrongly implemented as plain-insert.
        """
        conn = _make_conn()
        record_preference("response_style", "concise", user_id="peidong", conn=conn)
        record_preference("response_style", "verbose", user_id="peidong", conn=conn)
        prefs = list_preferences(user_id="peidong", conn=conn)
        assert len(prefs) == 1, f"expected 1 row after upsert; got {len(prefs)}"
        assert prefs[0].attributes["value"] == "verbose"
        assert prefs[0].evidence["declared_by"] == "peidong"

    def test_upsert_preserves_created_at(self) -> None:
        """Upsert update preserves the original created_at (ADR-020 D2).

        Discriminating: reverts SET … created_at = ts (the bug) → created_at becomes
        t2 → both == 1000 asserts fail.
        """
        conn = _make_conn()
        e1 = record_preference(
            "response_style", "concise", user_id="peidong", conn=conn, now=TimestampMs(1000)
        )
        e2 = record_preference(
            "response_style", "verbose", user_id="peidong", conn=conn, now=TimestampMs(2000)
        )
        prefs = list_preferences(user_id="peidong", conn=conn)
        assert len(prefs) == 1  # still one row (upsert, not append)
        assert prefs[0].attributes["value"] == "verbose"  # latest-wins value
        assert prefs[0].created_at == 1000  # persisted row keeps t1, NOT t2
        assert e1.created_at == 1000  # sanity: first call reports t1
        assert e2.created_at == 1000  # second call's returned Entity also reports t1

    def test_different_users_different_rows(self) -> None:
        conn = _make_conn()
        record_preference("response_style", "concise", user_id="peidong", conn=conn)
        record_preference("response_style", "verbose", user_id="alice", conn=conn)
        peidong_prefs = list_preferences(user_id="peidong", conn=conn)
        alice_prefs = list_preferences(user_id="alice", conn=conn)
        assert len(peidong_prefs) == 1
        assert len(alice_prefs) == 1
        assert peidong_prefs[0].attributes["value"] == "concise"
        assert alice_prefs[0].attributes["value"] == "verbose"

    def test_different_keys_different_rows(self) -> None:
        conn = _make_conn()
        record_preference("lang", "en", user_id="peidong", conn=conn)
        record_preference("response_style", "concise", user_id="peidong", conn=conn)
        prefs = list_preferences(user_id="peidong", conn=conn)
        assert len(prefs) == 2

    def test_scope_stored(self) -> None:
        conn = _make_conn()
        pref = record_preference("lang", "zh", user_id="u", scope=EntityScope.GLOBAL, conn=conn)
        assert pref.scope == EntityScope.GLOBAL
        loaded = get_entity_by_id(pref.id, conn)
        assert loaded is not None
        assert loaded.scope == EntityScope.GLOBAL

    def test_different_scopes_are_distinct_upsert_keys(self) -> None:
        """Same user+key in PERSONAL vs GLOBAL scope → two distinct rows."""
        conn = _make_conn()
        record_preference("lang", "en", user_id="u", scope=EntityScope.PERSONAL, conn=conn)
        record_preference("lang", "zh", user_id="u", scope=EntityScope.GLOBAL, conn=conn)
        personal = list_preferences(user_id="u", scope=EntityScope.PERSONAL, conn=conn)
        global_ = list_preferences(user_id="u", scope=EntityScope.GLOBAL, conn=conn)
        assert len(personal) == 1 and personal[0].attributes["value"] == "en"
        assert len(global_) == 1 and global_[0].attributes["value"] == "zh"

    def test_now_override(self) -> None:
        conn = _make_conn()
        ts = TimestampMs(1_700_000_000_000)
        pref = record_preference("k", "v", user_id="u", conn=conn, now=ts)
        assert pref.created_at == ts


# ---------------------------------------------------------------------------
# list_preferences
# ---------------------------------------------------------------------------


class TestListPreferences:
    def test_empty_db_returns_empty(self) -> None:
        conn = _make_conn()
        assert list_preferences(conn=conn) == []

    def test_filters_to_preference_type_only(self) -> None:
        conn = _make_conn()
        record_entity(EntityType.PROJECT, {}, conn=conn)
        record_preference("k", "v", user_id="u", conn=conn)
        prefs = list_preferences(conn=conn)
        assert len(prefs) == 1
        assert prefs[0].type == EntityType.PREFERENCE

    def test_user_id_filter(self) -> None:
        conn = _make_conn()
        record_preference("lang", "en", user_id="alice", conn=conn)
        record_preference("lang", "zh", user_id="bob", conn=conn)
        alice = list_preferences(user_id="alice", conn=conn)
        bob = list_preferences(user_id="bob", conn=conn)
        assert len(alice) == 1 and alice[0].evidence["declared_by"] == "alice"
        assert len(bob) == 1 and bob[0].evidence["declared_by"] == "bob"

    def test_no_user_id_returns_all_prefs(self) -> None:
        conn = _make_conn()
        record_preference("lang", "en", user_id="alice", conn=conn)
        record_preference("lang", "zh", user_id="bob", conn=conn)
        all_prefs = list_preferences(conn=conn)
        assert len(all_prefs) == 2

    def test_declared_by_provenance_present(self) -> None:
        conn = _make_conn()
        record_preference("response_style", "concise", user_id="peidong", conn=conn)
        prefs = list_preferences(user_id="peidong", conn=conn)
        assert prefs[0].evidence["declared_by"] == "peidong"
