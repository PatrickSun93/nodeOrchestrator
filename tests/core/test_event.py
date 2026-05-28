"""Tests for Event, EventType, metadata schemas, and validators in event.py.

These cover pure data shape — no DB, no I/O. Schema-level enforcement
is tested in test_constitution.py; store behaviors in test_event_store.py.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from typing import Any

from orchestrator.core.event import (
    DecisionMeta,
    Event,
    EventId,
    EventType,
    HypothesisMeta,
    MetadataValidationError,
    RejectionMeta,
    Relation,
    RelationType,
    RetractionMeta,
    RoomId,
    SummarySnapshotMeta,
    TimestampMs,
    ToolCallMeta,
    ToolResultMeta,
    is_valid_author,
    now_ms,
    validate_metadata,
)

# ---------------------------------------------------------------------------
# Author format
# ---------------------------------------------------------------------------


class TestIsValidAuthor:
    @pytest.mark.parametrize(
        "valid",
        [
            "user",
            "system",
            "agent:operator",
            "agent:skeptic",
            "agent:my-custom_agent_v2",
            "agent:a",
        ],
    )
    def test_valid(self, valid: str) -> None:
        assert is_valid_author(valid)

    @pytest.mark.parametrize(
        "invalid",
        [
            "",
            "User",
            "USER",
            "agent",
            "agent:",
            "agent:bad name",
            "agent:bad/name",
            "agent: trailing",
            "human",
            "user:1",
        ],
    )
    def test_invalid(self, invalid: str) -> None:
        assert not is_valid_author(invalid)


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


class TestEvent:
    def test_minimal_construction(self) -> None:
        e = Event(
            id=EventId("evt_min"),
            room_id=RoomId("room_min"),
            type=EventType.UTTERANCE,
            author="user",
            timestamp=now_ms(),
            content="hi",
        )
        assert e.parent_id is None
        assert e.metadata == {}
        assert e.type == EventType.UTTERANCE

    def test_event_is_frozen(self) -> None:
        e = Event(
            id=EventId("evt_x"),
            room_id=RoomId("room_x"),
            type=EventType.UTTERANCE,
            author="user",
            timestamp=now_ms(),
            content="hi",
        )
        with pytest.raises(ValidationError):
            e.content = "tampered"

    def test_event_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            Event(
                id=EventId("evt_x"),
                room_id=RoomId("room_x"),
                type=EventType.UTTERANCE,
                author="user",
                timestamp=now_ms(),
                content="hi",
                extra="not allowed",  # type: ignore[call-arg]
            )

    @pytest.mark.parametrize("bad_author", ["", "human", "agent:", "User", "USER"])
    def test_event_rejects_invalid_author(self, bad_author: str) -> None:
        with pytest.raises(ValidationError):
            Event(
                id=EventId("evt_x"),
                room_id=RoomId("room_x"),
                type=EventType.UTTERANCE,
                author=bad_author,
                timestamp=now_ms(),
                content="hi",
            )

    def test_all_16_event_types_constructible(self) -> None:
        """Sanity: every EventType value can be set on an Event without
        any per-type schema requirement firing (raw construction only)."""
        for et in EventType:
            e = Event(
                id=EventId("evt_x"),
                room_id=RoomId("room_x"),
                type=et,
                author="user",
                timestamp=now_ms(),
                content="hi",
            )
            assert e.type == et


# ---------------------------------------------------------------------------
# Per-type metadata schemas
# ---------------------------------------------------------------------------


class TestHypothesisMeta:
    def test_minimal_valid(self) -> None:
        m = HypothesisMeta(confidence=0.5)
        assert m.confidence == 0.5
        assert m.based_on == []

    @pytest.mark.parametrize("bad", [-0.1, 1.5, 2.0, -1.0])
    def test_confidence_out_of_range(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            HypothesisMeta(confidence=bad)

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            HypothesisMeta(confidence=0.5, extra="x")  # type: ignore[call-arg]

    def test_frozen(self) -> None:
        m = HypothesisMeta(confidence=0.5)
        with pytest.raises(ValidationError):
            m.confidence = 0.9


class TestDecisionMeta:
    def test_requires_at_least_one_based_on(self) -> None:
        with pytest.raises(ValidationError):
            DecisionMeta(based_on=[])

    def test_with_based_on(self) -> None:
        m = DecisionMeta(based_on=[EventId("evt_a"), EventId("evt_b")])
        assert len(m.based_on) == 2
        assert m.trade_offs == {}

    def test_with_trade_offs(self) -> None:
        m = DecisionMeta(
            based_on=[EventId("evt_a")],
            trade_offs={"speed": "fast", "complexity": "moderate"},
        )
        assert m.trade_offs["speed"] == "fast"


class TestRejectionMeta:
    def test_requires_rejects_and_reason(self) -> None:
        m = RejectionMeta(rejects=EventId("evt_x"), reason="bad assumption")
        assert m.rejects == "evt_x"
        assert m.reason == "bad assumption"

    def test_empty_reason_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RejectionMeta(rejects=EventId("evt_x"), reason="")


class TestRetractionMeta:
    def test_requires_retracts_and_reason(self) -> None:
        m = RetractionMeta(retracts=EventId("evt_x"), reason="reconsidered")
        assert m.retracts == "evt_x"
        assert m.reason == "reconsidered"

    def test_empty_reason_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetractionMeta(retracts=EventId("evt_x"), reason="")


class TestToolCallMeta:
    def test_minimal(self) -> None:
        m = ToolCallMeta(tool_name="web_search", call_id="c1")
        assert m.tool_name == "web_search"
        assert m.call_id == "c1"
        assert m.params == {}

    def test_with_params(self) -> None:
        m = ToolCallMeta(
            tool_name="search_text",
            call_id="c1",
            params={"query": "test", "scope": "all"},
        )
        assert m.params["query"] == "test"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolCallMeta(tool_name="", call_id="c1")

    def test_empty_call_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolCallMeta(tool_name="web_search", call_id="")


class TestToolResultMeta:
    def test_minimal(self) -> None:
        m = ToolResultMeta(call_id="c1", success=True)
        assert m.success is True
        assert m.output_truncated_at is None
        assert m.error_class is None

    def test_with_optional_fields(self) -> None:
        m = ToolResultMeta(
            call_id="c1",
            success=False,
            output_truncated_at=4096,
            error_class="TimeoutError",
        )
        assert m.output_truncated_at == 4096
        assert m.error_class == "TimeoutError"


# ---------------------------------------------------------------------------
# validate_metadata dispatcher
# ---------------------------------------------------------------------------


class TestValidateMetadata:
    def test_typed_event_validates(self) -> None:
        normalized = validate_metadata(EventType.HYPOTHESIS, {"confidence": 0.5})
        assert normalized == {"confidence": 0.5, "based_on": []}

    def test_typed_event_invalid_metadata_raises(self) -> None:
        with pytest.raises(MetadataValidationError):
            validate_metadata(EventType.HYPOTHESIS, {"confidence": 2.0})

    def test_typed_event_missing_required_raises(self) -> None:
        with pytest.raises(MetadataValidationError):
            validate_metadata(EventType.DECISION, {"trade_offs": {}})

    def test_untyped_event_passthrough(self) -> None:
        meta = {"anything": "goes", "nested": {"ok": True}}
        assert validate_metadata(EventType.UTTERANCE, meta) == meta

    def test_untyped_event_empty_passthrough(self) -> None:
        assert validate_metadata(EventType.USER_INPUT, {}) == {}

    def test_typed_extra_field_rejected(self) -> None:
        with pytest.raises(MetadataValidationError):
            validate_metadata(
                EventType.HYPOTHESIS,
                {"confidence": 0.5, "extra": "x"},
            )

    def test_normalization_fills_defaults(self) -> None:
        """For typed types, output dict has all fields including defaults."""
        normalized = validate_metadata(EventType.TOOL_RESULT, {"call_id": "c1", "success": True})
        assert normalized == {
            "call_id": "c1",
            "success": True,
            "output_truncated_at": None,
            "error_class": None,
        }


# ---------------------------------------------------------------------------
# Relation
# ---------------------------------------------------------------------------


class TestRelation:
    def test_relation_construction(self) -> None:
        r = Relation(
            event_id=EventId("evt_a"),
            relation_type=RelationType.REPLIES_TO,
            target_event_id=EventId("evt_b"),
            extracted_at=TimestampMs(123),
        )
        assert r.event_id == "evt_a"
        assert r.target_event_id == "evt_b"

    def test_relation_is_frozen(self) -> None:
        r = Relation(
            event_id=EventId("evt_a"),
            relation_type=RelationType.REPLIES_TO,
            target_event_id=EventId("evt_b"),
            extracted_at=now_ms(),
        )
        with pytest.raises(ValidationError):
            r.event_id = EventId("evt_x")

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            Relation(
                event_id=EventId("evt_a"),
                relation_type=RelationType.REPLIES_TO,
                target_event_id=EventId("evt_b"),
                extracted_at=now_ms(),
                extra="not allowed",  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# SummarySnapshotMeta — §6 schema invariants + round-trip (P1.6-2)
# ---------------------------------------------------------------------------

_SUMMARY_SNAPSHOT_REQUIRED_FIELDS: dict[str, Any] = {
    "room_id": "room_42",
    "room_type": "research",
    "room_state": "snapshot_pending",
    "snapshot_at": 1234567890,
    "event_count": 5,
    "decision_count": 2,
    "open_hypotheses": [{"event_id": "evt_h1"}],
    "closed_decisions": [{"event_id": "evt_d1"}],
    "tool_calls_pending_confirm": [],
    "last_state_transition": None,
    "participants": ["alpha", "logger"],
}


class TestSummarySnapshotMeta:
    def test_frozen(self) -> None:
        """SummarySnapshotMeta is frozen — mutating a field raises."""
        meta = SummarySnapshotMeta(**_SUMMARY_SNAPSHOT_REQUIRED_FIELDS)
        with pytest.raises(ValidationError):
            meta.room_state = "closed"

    def test_extra_forbid(self) -> None:
        """SummarySnapshotMeta rejects unknown fields."""
        with pytest.raises(ValidationError):
            SummarySnapshotMeta(
                **_SUMMARY_SNAPSHOT_REQUIRED_FIELDS,
                unknown_field="boom",  # type: ignore[call-arg]
            )

    def test_required_field_absent(self) -> None:
        """Omitting room_id → ValidationError."""
        fields = dict(_SUMMARY_SNAPSHOT_REQUIRED_FIELDS)
        del fields["room_id"]
        with pytest.raises(ValidationError):
            SummarySnapshotMeta(**fields)

    def test_wrong_type_event_count(self) -> None:
        """event_count ge=0 — negative value raises ValidationError."""
        fields = dict(_SUMMARY_SNAPSHOT_REQUIRED_FIELDS)
        fields["event_count"] = -1
        with pytest.raises(ValidationError):
            SummarySnapshotMeta(**fields)

    def test_validate_metadata_roundtrip(self) -> None:
        """validate_metadata(SUMMARY_SNAPSHOT, ...) succeeds and returns normalized dict."""
        meta = validate_metadata(
            EventType.SUMMARY_SNAPSHOT, dict(_SUMMARY_SNAPSHOT_REQUIRED_FIELDS)
        )
        assert meta["room_id"] == "room_42"
        assert meta["room_state"] == "snapshot_pending"
        assert meta["event_count"] == 5

    def test_snapshot_roundtrip(self) -> None:
        """Snapshot.model_dump() → SummarySnapshotMeta.model_validate() round-trips cleanly.

        Per ADR-014 D5: deliberate duplication invariant — the serialized Snapshot
        dict can be validated by SummarySnapshotMeta without data loss.
        """
        from orchestrator.core.event import generate_room_id
        from orchestrator.core.room import Room, RoomType
        from orchestrator.derived.snapshot import produce_snapshot

        room = Room(id=generate_room_id(), type=RoomType.RESEARCH, state="snapshot_pending")
        snapshot = produce_snapshot([], room, snapshot_at=TimestampMs(9999))
        snap_dict = snapshot.model_dump()

        meta = SummarySnapshotMeta.model_validate(snap_dict)
        assert meta.room_id == str(room.id)
        assert meta.room_state == "snapshot_pending"
        assert meta.event_count == 0
        assert meta.decision_count == 0
        assert meta.participants == []
