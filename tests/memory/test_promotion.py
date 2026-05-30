"""Tests for memory/promotion.py — promote_hypothesis.

Per plan P1.6.5-4 acceptance:
  - Happy path, HypothesisNotFoundError, PromotionEligibilityError,
    transaction atomicity (2 tests), correct decision event metadata,
    idempotence check, double-promote IntegrityError, status update.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from orchestrator.core.event import EventType, generate_event_id, generate_room_id
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.exceptions import HypothesisNotFoundError, PromotionEligibilityError
from orchestrator.memory.promotion import promote_hypothesis
from orchestrator.memory.schema import (
    HypothesisId,
    HypothesisStatus,
    VKScope,
)
from orchestrator.memory.store import (
    get_hypothesis_by_id,
    init_memory_schema,
    record_hypothesis,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_full_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return store, conn


def _seed(
    store: EventStore,
    conn: sqlite3.Connection,
    *,
    content: str = "claim X",
    confidence: float = 0.7,
    n_events: int = 2,
) -> tuple[Any, list[Any], Any]:
    from orchestrator.core.event import Event, EventType, TimestampMs, now_ms

    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    event_ids = []
    for i in range(n_events):
        evt = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.UTTERANCE,
            author="user",
            timestamp=TimestampMs(now_ms() + i),
            content=f"msg {i}",
        )
        store.append(evt)
        event_ids.append(evt.id)

    hyp = record_hypothesis(
        content=content,
        room_id=room.id,
        source_event_ids=event_ids,
        confidence=confidence,
        conn=conn,
    )
    return room.id, event_ids, hyp


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestPromoteHypothesisHappyPath:
    def test_returns_vk(self) -> None:
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        vk = promote_hypothesis(
            hyp.id,
            user_id="peidong",
            scope=VKScope.PERSONAL,
            topic_tags=["claim-x"],
            event_store=store,
        )
        assert vk.content == hyp.content
        assert vk.promoted_from_hypothesis_id == hyp.id
        assert vk.promoted_by_user_id == "peidong"
        assert vk.scope == VKScope.PERSONAL
        assert "claim-x" in vk.topic_tags

    def test_hypothesis_status_updated(self) -> None:
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        promote_hypothesis(hyp.id, user_id="u", scope=VKScope.PERSONAL, event_store=store)
        reloaded = get_hypothesis_by_id(hyp.id, conn=conn)
        assert reloaded is not None
        assert reloaded.status == HypothesisStatus.VERIFIED

    def test_vk_row_persisted(self) -> None:
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        vk = promote_hypothesis(hyp.id, user_id="u", scope=VKScope.TEAM, event_store=store)
        row = conn.execute(
            "SELECT * FROM verified_knowledge WHERE id = ?", (str(vk.id),)
        ).fetchone()
        assert row is not None
        assert row["promoted_from_hypothesis_id"] == str(hyp.id)

    def test_decision_event_in_event_store(self) -> None:
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        vk = promote_hypothesis(
            hyp.id,
            user_id="u",
            scope=VKScope.PERSONAL,
            event_store=store,
        )
        event = store.get_event(vk.promotion_event_id)
        assert event is not None
        assert event.type == EventType.DECISION
        assert event.metadata["promotion"] is True
        assert event.metadata["hypothesis_id"] == str(hyp.id)
        assert event.metadata["vk_id"] == str(vk.id)
        # impl-stage Y2: canonical event records the confirming user.
        assert event.metadata["user_id"] == "u"
        assert event.author == "system"  # subsystem executed; user_id is who confirmed

    def test_promotion_event_room_id_is_hypothesis_room(self) -> None:
        """Per ADR-016 D3 + Y5 alpha-(a): promotion event room_id = originating
        hypothesis's room_id."""
        store, conn = _make_full_store()
        room_id, _eids, hyp = _seed(store, conn)
        vk = promote_hypothesis(hyp.id, user_id="u", scope=VKScope.PERSONAL, event_store=store)
        event = store.get_event(vk.promotion_event_id)
        assert event is not None
        assert str(event.room_id) == str(room_id)

    def test_based_on_equals_source_event_ids(self) -> None:
        """Decision event based_on cites original source events."""
        store, conn = _make_full_store()
        _rid, event_ids, hyp = _seed(store, conn)
        vk = promote_hypothesis(hyp.id, user_id="u", scope=VKScope.GLOBAL, event_store=store)
        event = store.get_event(vk.promotion_event_id)
        assert event is not None
        assert sorted(event.metadata["based_on"]) == sorted([str(e) for e in event_ids])


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestPromoteHypothesisErrors:
    def test_not_found_raises(self) -> None:
        store, _conn = _make_full_store()
        with pytest.raises(HypothesisNotFoundError) as exc_info:
            promote_hypothesis(
                HypothesisId("hyp_" + "0" * 32),
                user_id="u",
                scope=VKScope.PERSONAL,
                event_store=store,
            )
        assert exc_info.value.hyp_id == "hyp_" + "0" * 32

    def test_non_pending_raises_eligibility_error(self) -> None:
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        # Promote once.
        promote_hypothesis(hyp.id, user_id="u", scope=VKScope.PERSONAL, event_store=store)
        # Second attempt: status is now VERIFIED.
        with pytest.raises(PromotionEligibilityError) as exc_info:
            promote_hypothesis(hyp.id, user_id="u", scope=VKScope.PERSONAL, event_store=store)
        assert exc_info.value.reason == "not_pending"

    def test_rejected_status_raises(self) -> None:
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        conn.execute("UPDATE hypothesis SET status = 'rejected' WHERE id = ?", (str(hyp.id),))
        conn.commit()
        with pytest.raises(PromotionEligibilityError):
            promote_hypothesis(hyp.id, user_id="u", scope=VKScope.PERSONAL, event_store=store)

    def test_stale_status_raises(self) -> None:
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        conn.execute("UPDATE hypothesis SET status = 'stale' WHERE id = ?", (str(hyp.id),))
        conn.commit()
        with pytest.raises(PromotionEligibilityError):
            promote_hypothesis(hyp.id, user_id="u", scope=VKScope.PERSONAL, event_store=store)


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------


class TestPromoteHypothesisAtomicity:
    def test_atomicity_vk_insert_fails_rolls_back_event(self) -> None:
        """Atomicity test 1: VK INSERT fails → event NOT in store + status PENDING.

        Triggered naturally: pre-insert a fake VK row with the same
        promoted_from_hypothesis_id (UNIQUE constraint violation at VK INSERT).
        This verifies ADR-016 D11 atomicity: all three writes share one transaction.
        """

        store, conn = _make_full_store()
        _rid, event_ids, hyp = _seed(store, conn)

        # Pre-insert a VK row that will conflict with promotion's VK INSERT.
        # Use an existing event_id as promotion_event_id to satisfy the FK.
        fake_vk_id = "vk_" + "f" * 32
        conn.execute(
            """INSERT INTO verified_knowledge
                   (id, content, topic_tags, evidence, last_validated,
                    contradictions, scope, promoted_from_hypothesis_id,
                    promoted_by_user_id, promotion_event_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fake_vk_id,
                "fake",
                "[]",
                "{}",
                1,
                "[]",
                "personal",
                str(hyp.id),  # same promoted_from_hypothesis_id → UNIQUE violation
                "fake_user",
                str(event_ids[0]),  # valid FK to events table
            ),
        )
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            promote_hypothesis(hyp.id, user_id="u", scope=VKScope.PERSONAL, event_store=store)

        # Decision event must NOT be in store (rolled back with VK INSERT failure).
        decision_rows = conn.execute(
            "SELECT COUNT(*) FROM events WHERE type = 'decision'"
        ).fetchone()[0]
        assert decision_rows == 0, "decision event must be rolled back on VK INSERT failure"

        # Hypothesis status must remain PENDING (UPDATE rolled back).
        reloaded = get_hypothesis_by_id(hyp.id, conn=conn)
        assert reloaded is not None
        assert reloaded.status == HypothesisStatus.PENDING

    def test_atomicity_append_fails_rolls_back(self) -> None:
        """Atomicity test 2: event append fails → no VK row + status PENDING.

        Uses patch.object to inject failure at append_in_transaction.
        """
        from unittest.mock import patch

        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)

        with (
            patch.object(store, "append_in_transaction", side_effect=RuntimeError("injected")),
            pytest.raises(RuntimeError, match="injected"),
        ):
            promote_hypothesis(hyp.id, user_id="u", scope=VKScope.PERSONAL, event_store=store)

        # No VK row.
        vk_count = conn.execute("SELECT COUNT(*) FROM verified_knowledge").fetchone()[0]
        assert vk_count == 0

        # Hypothesis status must remain PENDING (UPDATE rolled back).
        reloaded = get_hypothesis_by_id(hyp.id, conn=conn)
        assert reloaded is not None
        assert reloaded.status == HypothesisStatus.PENDING

    def test_double_promote_unique_constraint(self) -> None:
        """Double-promotion schema backstop (external Y9):

        A second VK INSERT with the same promoted_from_hypothesis_id raises
        sqlite3.IntegrityError (UNIQUE constraint), independent of the
        status-check gate.
        """
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        # First promotion: bypass status check by directly setting PENDING after.
        promote_hypothesis(hyp.id, user_id="u", scope=VKScope.PERSONAL, event_store=store)
        # Force status back to PENDING to bypass the eligibility check.
        conn.execute("UPDATE hypothesis SET status = 'pending' WHERE id = ?", (str(hyp.id),))
        conn.commit()
        # Second promotion: schema UNIQUE on promoted_from_hypothesis_id fires.
        with pytest.raises(sqlite3.IntegrityError):
            promote_hypothesis(hyp.id, user_id="u", scope=VKScope.PERSONAL, event_store=store)


# ---------------------------------------------------------------------------
# VK write-path wiring + atomicity (P2.1-5, ADR-018 D6 + D4)
# ---------------------------------------------------------------------------


class TestPromoteHypothesisTopicTagsWiring:
    def test_topic_tags_stored_canonical(self) -> None:
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        vk = promote_hypothesis(
            hyp.id,
            user_id="u",
            scope=VKScope.PERSONAL,
            topic_tags=["LLM Cost"],
            event_store=store,
        )
        assert vk.topic_tags == ["llm-cost"]
        row = conn.execute(
            "SELECT topic_tags FROM verified_knowledge WHERE id = ?", (str(vk.id),)
        ).fetchone()
        import json

        assert json.loads(row["topic_tags"]) == ["llm-cost"]

    def test_tag_registered_on_promotion(self) -> None:
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        promote_hypothesis(
            hyp.id,
            user_id="u",
            scope=VKScope.PERSONAL,
            topic_tags=["cross-room"],
            event_store=store,
        )
        row = conn.execute("SELECT canonical FROM tag WHERE canonical = 'cross-room'").fetchone()
        assert row is not None

    def test_tag_registration_rolls_back_with_vk_insert_failure(self) -> None:
        """Tag registration inside promotion transaction rolls back on VK INSERT failure."""
        from unittest.mock import patch

        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)

        with (
            patch.object(store, "append_in_transaction", side_effect=RuntimeError("inject")),
            pytest.raises(RuntimeError),
        ):
            promote_hypothesis(
                hyp.id,
                user_id="u",
                scope=VKScope.PERSONAL,
                topic_tags=["should-rollback"],
                event_store=store,
            )

        tag_count = conn.execute("SELECT COUNT(*) FROM tag").fetchone()[0]
        assert tag_count == 0, "tag registration must roll back with the transaction"

    def test_whitespace_only_topic_tag_raises_value_error(self) -> None:
        """Contract tightening (G3): empty-normalizing tag raises ValueError."""
        store, conn = _make_full_store()
        _rid, _eids, hyp = _seed(store, conn)
        with pytest.raises(ValueError, match="normalizes to empty string"):
            promote_hypothesis(
                hyp.id,
                user_id="u",
                scope=VKScope.PERSONAL,
                topic_tags=["   "],
                event_store=store,
            )
