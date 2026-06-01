"""Tests for reentry/schema.py — NewSinceLeaveItem, ReentryDigest, ReentryResult.

Coverage standard:
  §6 schema invariants — frozen + extra="forbid" for each model.
  §5 N/A — no boundary validators with multi-position collection guards.
  §1 N/A — schema models are pure data; cross-module integration in e2e test.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.core.event import RoomId, TimestampMs, generate_room_id
from orchestrator.reentry.schema import NewSinceLeaveItem, ReentryDigest, ReentryResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_digest(room_id: RoomId | None = None) -> ReentryDigest:
    return ReentryDigest(
        room_id=room_id or generate_room_id(),
        archive=None,
        recalled_knowledge=[],
        entities=[],
        preferences=[],
        new_since_leave=[],
        last_seen_ts=None,
        generated_at=TimestampMs(1000),
    )


# ---------------------------------------------------------------------------
# §6 NewSinceLeaveItem schema invariants
# ---------------------------------------------------------------------------


class TestNewSinceLeaveItemSchema:
    def test_frozen_raises_on_mutation(self) -> None:
        item = NewSinceLeaveItem(
            fact_type="event",
            ref_id="evt_abc",
            label="something happened",
            occurred_at=TimestampMs(500),
        )
        with pytest.raises((ValidationError, TypeError)):
            item.label = "changed"

    def test_extra_forbid_raises(self) -> None:
        with pytest.raises(ValidationError):
            NewSinceLeaveItem(  # type: ignore[call-arg]
                fact_type="event",
                ref_id="evt_abc",
                label="x",
                occurred_at=TimestampMs(1),
                unknown_field="oops",
            )

    def test_fact_type_literal_verified_knowledge_accepted(self) -> None:
        item = NewSinceLeaveItem(
            fact_type="verified_knowledge",
            ref_id="vk_abc",
            label="some fact",
            occurred_at=TimestampMs(100),
        )
        assert item.fact_type == "verified_knowledge"

    def test_fact_type_literal_event_accepted(self) -> None:
        item = NewSinceLeaveItem(
            fact_type="event",
            ref_id="evt_abc",
            label="an event",
            occurred_at=TimestampMs(200),
        )
        assert item.fact_type == "event"

    def test_fact_type_only_valid_literals_accepted(self) -> None:
        vk = NewSinceLeaveItem(
            fact_type="verified_knowledge",
            ref_id="vk_abc",
            label="a known fact",
            occurred_at=TimestampMs(1),
        )
        evt = NewSinceLeaveItem(
            fact_type="event",
            ref_id="evt_abc",
            label="an event",
            occurred_at=TimestampMs(2),
        )
        assert vk.fact_type == "verified_knowledge"
        assert evt.fact_type == "event"


# ---------------------------------------------------------------------------
# §6 ReentryDigest schema invariants
# ---------------------------------------------------------------------------


class TestReentryDigestSchema:
    def test_reentry_digest_frozen_raises_on_mutation(self) -> None:
        digest = _make_digest()
        with pytest.raises((ValidationError, TypeError)):
            digest.last_seen_ts = 999

    def test_extra_forbid_raises(self) -> None:
        with pytest.raises(ValidationError):
            ReentryDigest(  # type: ignore[call-arg]
                room_id=generate_room_id(),
                archive=None,
                recalled_knowledge=[],
                entities=[],
                preferences=[],
                new_since_leave=[],
                last_seen_ts=None,
                generated_at=TimestampMs(1),
                unknown_extra="bad",
            )

    def test_new_since_leave_is_list_of_items_not_dict(self) -> None:
        item = NewSinceLeaveItem(
            fact_type="event",
            ref_id="evt_x",
            label="label",
            occurred_at=TimestampMs(100),
        )
        digest = ReentryDigest(
            room_id=generate_room_id(),
            archive=None,
            recalled_knowledge=[],
            entities=[],
            preferences=[],
            new_since_leave=[item],
            last_seen_ts=None,
            generated_at=TimestampMs(1000),
        )
        assert isinstance(digest.new_since_leave[0], NewSinceLeaveItem)
        assert digest.new_since_leave[0].fact_type == "event"

    def test_last_seen_ts_none_allowed(self) -> None:
        digest = _make_digest()
        assert digest.last_seen_ts is None

    def test_last_seen_ts_int_allowed(self) -> None:
        digest = ReentryDigest(
            room_id=generate_room_id(),
            archive=None,
            recalled_knowledge=[],
            entities=[],
            preferences=[],
            new_since_leave=[],
            last_seen_ts=42000,
            generated_at=TimestampMs(1000),
        )
        assert digest.last_seen_ts == 42000


# ---------------------------------------------------------------------------
# §6 ReentryResult schema invariants
# ---------------------------------------------------------------------------


class TestReentryResultSchema:
    def test_reentry_result_frozen_raises_on_mutation(self) -> None:
        result = ReentryResult(digest=_make_digest(), prose="hello")
        with pytest.raises((ValidationError, TypeError)):
            result.prose = "changed"

    def test_extra_forbid_raises(self) -> None:
        with pytest.raises(ValidationError):
            ReentryResult(  # type: ignore[call-arg]
                digest=_make_digest(),
                prose="hello",
                unknown="oops",
            )
