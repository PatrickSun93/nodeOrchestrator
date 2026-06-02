"""§6 wire contract invariants: round-trip, extra-field rejection, forge guards.

These tests verify the inscribe-before-producer contract (ADR-025 D5):
the wire models serialize/deserialize correctly and the extra="forbid"
constraint rejects any identity fields (author, id, timestamp) that a
client might try to inject.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from orchestrator.api.wire import (
    INTENT_TYPE_ALLOWLIST,
    Event,
    IntentError,
    IntentRequest,
    IntentResponse,
    Room,
    Snapshot,
    StreamErrorMessage,
    StreamEventMessage,
    StreamReplayCompleteMessage,
    TurnResult,
)
from orchestrator.core.event import (
    EventId,
    EventType,
    RoomId,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.room import RoomType
from orchestrator.derived.snapshot import produce_snapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(room_id: RoomId) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.USER_INPUT,
        author="user",
        timestamp=now_ms(),
        content="hello",
    )


def _make_room(room_id: RoomId | None = None) -> Room:
    return Room(
        id=room_id or generate_room_id(),
        type=RoomType.FREE_CHAT,
    )


# ---------------------------------------------------------------------------
# §6.1  Event round-trip (frozen, extra="forbid")
# ---------------------------------------------------------------------------


class TestEventRoundTrip:
    def test_serialize_deserialize_roundtrip(self) -> None:
        room_id = generate_room_id()
        event = _make_event(room_id)
        data = event.model_dump()
        restored = Event.model_validate(data)
        assert restored == event

    def test_json_roundtrip(self) -> None:
        event = _make_event(generate_room_id())
        json_str = event.model_dump_json()
        restored = Event.model_validate_json(json_str)
        assert restored == event

    def test_extra_field_rejected(self) -> None:
        room_id = generate_room_id()
        data: dict[str, Any] = {
            "id": generate_event_id(),
            "room_id": room_id,
            "type": "user_input",
            "author": "user",
            "timestamp": now_ms(),
            "content": "hi",
            "extra_unknown": "forbidden",
        }
        with pytest.raises(ValidationError):
            Event.model_validate(data)

    def test_frozen_mutation_rejected(self) -> None:
        event = _make_event(generate_room_id())
        # frozen=True: direct attribute assignment must raise
        with pytest.raises(ValidationError):
            event.content = "mutated"


# ---------------------------------------------------------------------------
# §6.2  Room round-trip
# ---------------------------------------------------------------------------


class TestRoomRoundTrip:
    def test_serialize_deserialize_roundtrip(self) -> None:
        room = _make_room()
        data = room.model_dump()
        restored = Room.model_validate(data)
        assert restored == room

    def test_json_roundtrip(self) -> None:
        room = _make_room()
        json_str = room.model_dump_json()
        restored = Room.model_validate_json(json_str)
        assert restored == room

    def test_extra_field_rejected(self) -> None:
        data: dict[str, Any] = {
            "id": generate_room_id(),
            "type": "free_chat",
            "extra": "nope",
        }
        with pytest.raises(ValidationError):
            Room.model_validate(data)


# ---------------------------------------------------------------------------
# §6.3  Snapshot round-trip
# ---------------------------------------------------------------------------


class TestSnapshotRoundTrip:
    def test_serialize_deserialize_roundtrip(self) -> None:
        room = _make_room()
        snap = produce_snapshot([], room, snapshot_at=now_ms())
        data = snap.model_dump()
        restored = Snapshot.model_validate(data)
        assert restored == snap

    def test_json_roundtrip(self) -> None:
        room = _make_room()
        snap = produce_snapshot([], room, snapshot_at=now_ms())
        json_str = snap.model_dump_json()
        restored = Snapshot.model_validate_json(json_str)
        assert restored == snap


# ---------------------------------------------------------------------------
# §6.4  IntentRequest — forge guard (extra="forbid" rejects identity fields)
# ---------------------------------------------------------------------------


class TestIntentRequestForgeGuard:
    def test_valid_intent_round_trip(self) -> None:
        req = IntentRequest(type=EventType.USER_INPUT, content="hello")
        data = req.model_dump()
        restored = IntentRequest.model_validate(data)
        assert restored == req

    def test_rejects_author_field(self) -> None:
        with pytest.raises(ValidationError):
            IntentRequest.model_validate(
                {"type": "user_input", "content": "hi", "author": "system"}
            )

    def test_rejects_id_field(self) -> None:
        with pytest.raises(ValidationError):
            IntentRequest.model_validate({"type": "user_input", "content": "hi", "id": "evt_abc"})

    def test_rejects_timestamp_field(self) -> None:
        with pytest.raises(ValidationError):
            IntentRequest.model_validate(
                {"type": "user_input", "content": "hi", "timestamp": 123456}
            )

    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            IntentRequest.model_validate(
                {"type": "user_input", "content": "hi", "agent_id": "agent:foo"}
            )

    def test_with_optional_metadata_and_parent(self) -> None:
        req = IntentRequest(
            type=EventType.USER_INPUT,
            content="hello",
            metadata={"key": "val"},
            parent_id=EventId("evt_abc123"),
        )
        assert req.metadata == {"key": "val"}
        assert req.parent_id == EventId("evt_abc123")

    def test_json_roundtrip(self) -> None:
        req = IntentRequest(type=EventType.USER_INPUT, content="hello")
        restored = IntentRequest.model_validate_json(req.model_dump_json())
        assert restored == req


# ---------------------------------------------------------------------------
# §6.5  IntentError — stage discriminator
# ---------------------------------------------------------------------------


class TestIntentError:
    def test_append_stage_no_event_id(self) -> None:
        err = IntentError(stage="append", appended_event_id=None, reason="room missing")
        assert err.stage == "append"
        assert err.appended_event_id is None

    def test_turn_stage_with_event_id(self) -> None:
        eid = generate_event_id()
        err = IntentError(stage="turn", appended_event_id=eid, reason="LLM failed")
        assert err.stage == "turn"
        assert err.appended_event_id == eid

    def test_json_roundtrip(self) -> None:
        err = IntentError(stage="turn", appended_event_id=generate_event_id(), reason="x")
        restored = IntentError.model_validate_json(err.model_dump_json())
        assert restored == err


# ---------------------------------------------------------------------------
# §6.6  StreamMessage discriminated union
# ---------------------------------------------------------------------------


class TestStreamMessage:
    def test_event_message_roundtrip(self) -> None:
        event = _make_event(generate_room_id())
        msg = StreamEventMessage(event=event)
        assert msg.kind == "event"
        data = msg.model_dump()
        restored = StreamEventMessage.model_validate(data)
        assert restored == msg

    def test_error_message_roundtrip(self) -> None:
        msg = StreamErrorMessage(stage="turn", reason="fail")
        assert msg.kind == "error"
        data = msg.model_dump()
        restored = StreamErrorMessage.model_validate(data)
        assert restored == msg

    def test_replay_complete_roundtrip(self) -> None:
        msg = StreamReplayCompleteMessage()
        assert msg.kind == "replay_complete"
        data = msg.model_dump()
        restored = StreamReplayCompleteMessage.model_validate(data)
        assert restored == msg

    def test_replay_complete_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StreamReplayCompleteMessage.model_validate({"kind": "replay_complete", "x": 1})


# ---------------------------------------------------------------------------
# §6.7  INTENT_TYPE_ALLOWLIST invariant
# ---------------------------------------------------------------------------


class TestIntentAllowlist:
    def test_allowlist_contains_expected_types(self) -> None:
        assert EventType.USER_INPUT in INTENT_TYPE_ALLOWLIST
        assert EventType.DECISION in INTENT_TYPE_ALLOWLIST
        assert EventType.RETRACTION in INTENT_TYPE_ALLOWLIST

    def test_utterance_excluded(self) -> None:
        assert EventType.UTTERANCE not in INTENT_TYPE_ALLOWLIST

    def test_state_transition_excluded(self) -> None:
        assert EventType.STATE_TRANSITION not in INTENT_TYPE_ALLOWLIST

    def test_autonomy_decision_excluded(self) -> None:
        assert EventType.AUTONOMY_DECISION not in INTENT_TYPE_ALLOWLIST

    def test_tool_call_excluded(self) -> None:
        assert EventType.TOOL_CALL not in INTENT_TYPE_ALLOWLIST


# ---------------------------------------------------------------------------
# §6.8  TurnResult re-export round-trip
# ---------------------------------------------------------------------------


class TestTurnResultRoundTrip:
    def test_empty_turn_result_roundtrip(self) -> None:
        turn = TurnResult(utterances=[], total_asked=0)
        data = turn.model_dump()
        restored = TurnResult.model_validate(data)
        assert restored == turn

    def test_with_utterance(self) -> None:
        room_id = generate_room_id()
        event = _make_event(room_id)
        turn = TurnResult(utterances=[event], total_asked=1)
        data = turn.model_dump()
        restored = TurnResult.model_validate(data)
        assert restored.utterances[0] == event


# ---------------------------------------------------------------------------
# §6.9  IntentResponse round-trip
# ---------------------------------------------------------------------------


class TestIntentResponseRoundTrip:
    def test_roundtrip(self) -> None:
        room_id = generate_room_id()
        event = _make_event(room_id)
        turn = TurnResult(utterances=[], total_asked=1, failed_agents=["agent:foo"])
        resp = IntentResponse(appended_event=event, turn=turn)
        data = resp.model_dump()
        restored = IntentResponse.model_validate(data)
        assert restored.appended_event == event
        assert restored.turn.failed_agents == ["agent:foo"]
