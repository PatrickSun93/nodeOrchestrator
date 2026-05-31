"""Tests for memory/matcher.py — run_matcher, MatcherResult.

Per plan P2.2-2 acceptance criteria (ADR-017 D1-D5).
"""

from __future__ import annotations

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
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.matcher import MatcherResult, run_matcher
from orchestrator.memory.store import (
    get_hypothesis_by_id,
    init_memory_schema,
    record_hypothesis,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_full_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return store, conn


def _make_room_with_events(store: EventStore, *, n_events: int = 1) -> tuple[RoomId, list[EventId]]:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    ids: list[EventId] = []
    base = now_ms()
    for i in range(n_events):
        evt = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.UTTERANCE,
            author="user",
            timestamp=TimestampMs(base + i),
            content=f"event {i}",
        )
        store.append(evt)
        ids.append(evt.id)
    return room.id, ids


# ---------------------------------------------------------------------------
# Basic contract
# ---------------------------------------------------------------------------


class TestRunMatcherContract:
    def test_min_rooms_zero_raises(self) -> None:
        _store, conn = _make_full_store()
        with pytest.raises(ValueError):
            run_matcher(conn, min_rooms=0)

    def test_min_rooms_negative_raises(self) -> None:
        _store, conn = _make_full_store()
        with pytest.raises(ValueError):
            run_matcher(conn, min_rooms=-1)

    def test_empty_hypothesis_table_returns_zero(self) -> None:
        _store, conn = _make_full_store()
        result = run_matcher(conn)
        assert result.groups_inspected == 0
        assert result.rows_newly_flagged == 0

    def test_returns_matcher_result(self) -> None:
        _store, conn = _make_full_store()
        result = run_matcher(conn)
        assert isinstance(result, MatcherResult)

    def test_scans_only_pending_rows(self) -> None:
        """Verified/rejected/stale hypotheses are excluded from grouping."""
        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        room2, evts2 = _make_room_with_events(store)
        h1 = record_hypothesis(
            content="claim",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=["llm-cost"],
        )
        h2 = record_hypothesis(
            content="claim",
            room_id=room2,
            source_event_ids=evts2,
            confidence=0.8,
            conn=conn,
            topic_tags=["llm-cost"],
        )
        # Manually set h2 to verified — should be excluded.
        conn.execute("UPDATE hypothesis SET status = 'verified' WHERE id = ?", (str(h2.id),))
        conn.commit()
        result = run_matcher(conn)
        # Only h1 is pending; only 1 room worth → no flag.
        assert result.rows_newly_flagged == 0
        loaded = get_hypothesis_by_id(h1.id, conn=conn)
        assert loaded is not None
        assert loaded.candidate_for_promotion is False


# ---------------------------------------------------------------------------
# Core grouping logic
# ---------------------------------------------------------------------------


class TestRunMatcherGrouping:
    def test_cross_room_same_tags_flagged(self) -> None:
        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        room2, evts2 = _make_room_with_events(store)
        h1 = record_hypothesis(
            content="c1",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=["llm-cost"],
        )
        h2 = record_hypothesis(
            content="c2",
            room_id=room2,
            source_event_ids=evts2,
            confidence=0.8,
            conn=conn,
            topic_tags=["llm-cost"],
        )
        result = run_matcher(conn)
        assert result.rows_newly_flagged == 2
        for hyp_id in (h1.id, h2.id):
            loaded = get_hypothesis_by_id(hyp_id, conn=conn)
            assert loaded is not None
            assert loaded.candidate_for_promotion is True

    def test_singleton_group_not_flagged(self) -> None:
        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        h = record_hypothesis(
            content="solo",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=["ml-ops"],
        )
        result = run_matcher(conn)
        assert result.rows_newly_flagged == 0
        loaded = get_hypothesis_by_id(h.id, conn=conn)
        assert loaded is not None
        assert loaded.candidate_for_promotion is False

    def test_distinct_room_not_distinct_row(self) -> None:
        """Same-room group: two rows in one room do NOT count as cross-room."""
        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store, n_events=2)
        h1 = record_hypothesis(
            content="a",
            room_id=room1,
            source_event_ids=[evts1[0]],
            confidence=0.8,
            conn=conn,
            topic_tags=["solo-topic"],
        )
        h2 = record_hypothesis(
            content="b",
            room_id=room1,
            source_event_ids=[evts1[1]],
            confidence=0.8,
            conn=conn,
            topic_tags=["solo-topic"],
        )
        result = run_matcher(conn, min_rooms=2)
        assert result.rows_newly_flagged == 0
        for hyp_id in (h1.id, h2.id):
            loaded = get_hypothesis_by_id(hyp_id, conn=conn)
            assert loaded is not None
            assert loaded.candidate_for_promotion is False

    def test_normalize_at_read_different_surface_forms(self) -> None:
        """Different surface forms normalize to the same key (ADR-017 D1/D2)."""
        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        room2, evts2 = _make_room_with_events(store)
        h1 = record_hypothesis(
            content="c1",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=["LLM Cost"],  # stores canonical "llm-cost"
        )
        h2 = record_hypothesis(
            content="c2",
            room_id=room2,
            source_event_ids=evts2,
            confidence=0.8,
            conn=conn,
            topic_tags=["llm cost"],  # stores canonical "llm-cost"
        )
        result = run_matcher(conn)
        assert result.rows_newly_flagged == 2
        for hyp_id in (h1.id, h2.id):
            loaded = get_hypothesis_by_id(hyp_id, conn=conn)
            assert loaded is not None
            assert loaded.candidate_for_promotion is True

    def test_empty_canonical_set_excluded(self) -> None:
        """Untagged hypotheses (empty topic_tags) never grouped — AC#2."""
        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        room2, evts2 = _make_room_with_events(store)
        h1 = record_hypothesis(
            content="c1",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=[],
        )
        h2 = record_hypothesis(
            content="c2",
            room_id=room2,
            source_event_ids=evts2,
            confidence=0.8,
            conn=conn,
            topic_tags=[],
        )
        result = run_matcher(conn, min_rooms=2)
        assert result.groups_inspected == 0
        assert result.rows_newly_flagged == 0
        for hyp_id in (h1.id, h2.id):
            loaded = get_hypothesis_by_id(hyp_id, conn=conn)
            assert loaded is not None
            assert loaded.candidate_for_promotion is False

    def test_untagged_across_rooms_zero_flagged(self) -> None:
        """AC#11: untagged across >=min_rooms rooms → zero flagged (A routing).

        This is the dominant early-life case (dormant-until-fed): most
        hypothesis rows are untagged until an auto-tagging producer ships.
        Without the empty-set exclusion, the matcher would false-positive-flag
        every untagged hypothesis across rooms. This test guards that regression.
        """
        store, conn = _make_full_store()
        rooms = [_make_room_with_events(store) for _ in range(3)]
        hyps = [
            record_hypothesis(
                content=f"untagged claim {i}",
                room_id=room_id,
                source_event_ids=evts,
                confidence=0.7,
                conn=conn,
                topic_tags=[],  # untagged — empty canonical set
            )
            for i, (room_id, evts) in enumerate(rooms)
        ]
        result = run_matcher(conn, min_rooms=2)
        assert result.groups_inspected == 0
        assert result.rows_newly_flagged == 0
        for hyp in hyps:
            loaded = get_hypothesis_by_id(hyp.id, conn=conn)
            assert loaded is not None
            assert loaded.candidate_for_promotion is False

    def test_min_rooms_respected(self) -> None:
        """min_rooms=3 requires three distinct rooms to flag."""
        store, conn = _make_full_store()
        rooms = [_make_room_with_events(store) for _ in range(2)]
        hyps = [
            record_hypothesis(
                content="c",
                room_id=room_id,
                source_event_ids=evts,
                confidence=0.8,
                conn=conn,
                topic_tags=["ml"],
            )
            for room_id, evts in rooms
        ]
        # 2 rooms, min_rooms=3 → no flag.
        result = run_matcher(conn, min_rooms=3)
        assert result.rows_newly_flagged == 0
        for hyp in hyps:
            loaded = get_hypothesis_by_id(hyp.id, conn=conn)
            assert loaded is not None
            assert loaded.candidate_for_promotion is False

        # Add a third room.
        room3, evts3 = _make_room_with_events(store)
        record_hypothesis(
            content="c",
            room_id=room3,
            source_event_ids=evts3,
            confidence=0.8,
            conn=conn,
            topic_tags=["ml"],
        )
        result2 = run_matcher(conn, min_rooms=3)
        assert result2.rows_newly_flagged == 3


# ---------------------------------------------------------------------------
# Determinism, idempotency, monotonicity
# ---------------------------------------------------------------------------


class TestRunMatcherInvariants:
    def test_idempotent_second_run_flags_nothing(self) -> None:
        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        room2, evts2 = _make_room_with_events(store)
        record_hypothesis(
            content="c",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=["llm"],
        )
        record_hypothesis(
            content="c",
            room_id=room2,
            source_event_ids=evts2,
            confidence=0.8,
            conn=conn,
            topic_tags=["llm"],
        )
        r1 = run_matcher(conn)
        r2 = run_matcher(conn)
        assert r1.rows_newly_flagged == 2
        assert r2.rows_newly_flagged == 0

    def test_monotonic_never_clears_flag(self) -> None:
        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        room2, evts2 = _make_room_with_events(store)
        h1 = record_hypothesis(
            content="c",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=["tag"],
        )
        record_hypothesis(
            content="c",
            room_id=room2,
            source_event_ids=evts2,
            confidence=0.8,
            conn=conn,
            topic_tags=["tag"],
        )
        run_matcher(conn)
        loaded = get_hypothesis_by_id(h1.id, conn=conn)
        assert loaded is not None
        assert loaded.candidate_for_promotion is True
        # Even if we run again, flag stays True.
        run_matcher(conn)
        reloaded = get_hypothesis_by_id(h1.id, conn=conn)
        assert reloaded is not None
        assert reloaded.candidate_for_promotion is True

    def test_determinism_scan_order_independence(self) -> None:
        """Flagged id-set is stable regardless of INSERT / scan order (AC#5).

        Shuffled record order is the proxy for SQLite scan-order independence.
        Flag correctness is by-construction via set operations; the sort is only
        for stable MatcherResult reporting.
        """
        store1, conn1 = _make_full_store()
        store2, conn2 = _make_full_store()

        # Room + event setup for both stores.
        def _seed(
            store: EventStore, conn: sqlite3.Connection, insert_order: list[int]
        ) -> list[str]:
            rooms = [_make_room_with_events(store) for _ in range(3)]
            hyps: list[str] = []
            for i in insert_order:
                room_id, evts = rooms[i % len(rooms)]
                h = record_hypothesis(
                    content=f"c{i}",
                    room_id=room_id,
                    source_event_ids=evts,
                    confidence=0.8,
                    conn=conn,
                    topic_tags=["cluster-tag"],
                )
                hyps.append(h.id)
            return hyps

        _seed(store1, conn1, insert_order=[0, 1, 2])
        _seed(store2, conn2, insert_order=[2, 0, 1])  # shuffled

        run_matcher(conn1)
        run_matcher(conn2)

        flagged1 = {
            row["id"]
            for row in conn1.execute(
                "SELECT id FROM hypothesis WHERE candidate_for_promotion = 1"
            ).fetchall()
        }
        flagged2 = {
            row["id"]
            for row in conn2.execute(
                "SELECT id FROM hypothesis WHERE candidate_for_promotion = 1"
            ).fetchall()
        }
        # Both stores have the same COUNT flagged (same structure, different IDs).
        assert len(flagged1) == len(flagged2) == 3


# ---------------------------------------------------------------------------
# list_promotion_candidates reader (P2.2-3, ADR-017 D6)
# ---------------------------------------------------------------------------


class TestListPromotionCandidates:
    def test_returns_empty_before_any_flagging(self) -> None:
        from orchestrator.memory.matcher import list_promotion_candidates

        _store, conn = _make_full_store()
        assert list_promotion_candidates(conn) == []

    def test_returns_flagged_pending_rows(self) -> None:
        from orchestrator.memory.matcher import list_promotion_candidates

        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        room2, evts2 = _make_room_with_events(store)
        h1 = record_hypothesis(
            content="c1",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=["ml"],
        )
        h2 = record_hypothesis(
            content="c2",
            room_id=room2,
            source_event_ids=evts2,
            confidence=0.8,
            conn=conn,
            topic_tags=["ml"],
        )
        run_matcher(conn)
        candidates = list_promotion_candidates(conn)
        ids = {c.id for c in candidates}
        assert h1.id in ids
        assert h2.id in ids
        assert len(candidates) == 2

    def test_excludes_non_flagged_rows(self) -> None:
        from orchestrator.memory.matcher import list_promotion_candidates

        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        room2, evts2 = _make_room_with_events(store)
        room3, evts3 = _make_room_with_events(store)
        h_cluster1 = record_hypothesis(
            content="cross-room",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=["cluster"],
        )
        h_cluster2 = record_hypothesis(
            content="cross-room",
            room_id=room2,
            source_event_ids=evts2,
            confidence=0.8,
            conn=conn,
            topic_tags=["cluster"],
        )
        h_singleton = record_hypothesis(
            content="solo",
            room_id=room3,
            source_event_ids=evts3,
            confidence=0.8,
            conn=conn,
            topic_tags=["unique-tag"],
        )
        run_matcher(conn)
        candidates = list_promotion_candidates(conn)
        ids = {c.id for c in candidates}
        assert h_cluster1.id in ids
        assert h_cluster2.id in ids
        assert h_singleton.id not in ids

    def test_excludes_verified_even_if_flag_set(self) -> None:
        """status='pending' filter — VERIFIED rows not returned even if flagged."""
        from orchestrator.memory.matcher import list_promotion_candidates

        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        room2, evts2 = _make_room_with_events(store)
        h1 = record_hypothesis(
            content="c",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=["t"],
        )
        h2 = record_hypothesis(
            content="c",
            room_id=room2,
            source_event_ids=evts2,
            confidence=0.8,
            conn=conn,
            topic_tags=["t"],
        )
        run_matcher(conn)
        # Manually mark h2 as verified.
        conn.execute("UPDATE hypothesis SET status = 'verified' WHERE id = ?", (str(h2.id),))
        conn.commit()
        candidates = list_promotion_candidates(conn)
        assert len(candidates) == 1
        assert candidates[0].id == h1.id

    def test_ordered_by_id_asc(self) -> None:
        from orchestrator.memory.matcher import list_promotion_candidates

        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store, n_events=3)
        room2, evts2 = _make_room_with_events(store, n_events=3)
        hyps = []
        for i in range(3):
            h = record_hypothesis(
                content=f"c{i}",
                room_id=room1 if i % 2 == 0 else room2,
                source_event_ids=[evts1[i] if i % 2 == 0 else evts2[i]],
                confidence=0.8,
                conn=conn,
                topic_tags=["ordered"],
            )
            hyps.append(h)
        run_matcher(conn)
        candidates = list_promotion_candidates(conn)
        ids = [c.id for c in candidates]
        assert ids == sorted(ids)

    def test_returns_hypothesis_models(self) -> None:
        from orchestrator.memory.matcher import list_promotion_candidates
        from orchestrator.memory.schema import Hypothesis

        store, conn = _make_full_store()
        room1, evts1 = _make_room_with_events(store)
        room2, evts2 = _make_room_with_events(store)
        record_hypothesis(
            content="c",
            room_id=room1,
            source_event_ids=evts1,
            confidence=0.8,
            conn=conn,
            topic_tags=["t"],
        )
        record_hypothesis(
            content="c",
            room_id=room2,
            source_event_ids=evts2,
            confidence=0.8,
            conn=conn,
            topic_tags=["t"],
        )
        run_matcher(conn)
        candidates = list_promotion_candidates(conn)
        for c in candidates:
            assert isinstance(c, Hypothesis)
            assert c.candidate_for_promotion is True
