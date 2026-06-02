"""§4 boundary/validation + §1 write e2e — intent endpoint forge-prevention + run_turn.

Covers:
  - §4: Forge-prevention fail-closed (allowlist, author-stamping, metadata validation)
  - §4: IntentRequest extra="forbid" rejects identity fields
  - §4: Authority check — DECISION{promotion:true} appends but does not promote
  - §1 write e2e: POST intent → append(author:user) → run_turn → events stream to WS
  - Discriminating: correct events surface (type, author, content)
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from fastapi.testclient import TestClient

from orchestrator.api.app import AppContext
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    generate_event_id,
    now_ms,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_room(client: TestClient, room_type: str = "free_chat") -> str:
    r = client.post("/rooms", json={"type": room_type})
    assert r.status_code == 201
    result: str = r.json()["id"]
    return result


# ---------------------------------------------------------------------------
# §4.1  Basic success — author server-stamped "user"
# ---------------------------------------------------------------------------


class TestIntentBasicSuccess:
    def test_intent_returns_200_with_appended_event(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "hello"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "appended_event" in data
        assert "turn" in data

    def test_author_is_server_stamped_as_user(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "test"},
        )
        assert r.status_code == 200
        evt = r.json()["appended_event"]
        assert evt["author"] == "user"

    def test_id_and_timestamp_are_server_stamped(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "test"},
        )
        assert r.status_code == 200
        evt = r.json()["appended_event"]
        assert evt["id"].startswith("evt_")
        assert isinstance(evt["timestamp"], int)
        assert evt["timestamp"] > 0

    def test_event_appears_in_get_events(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "store me"},
        )
        assert r.status_code == 200
        evt_id = r.json()["appended_event"]["id"]

        events = client.get(f"/rooms/{room_id}/events").json()
        found_ids = {e["id"] for e in events}
        assert evt_id in found_ids


# ---------------------------------------------------------------------------
# §4.2  Forge-prevention: extra="forbid" rejects identity fields
# ---------------------------------------------------------------------------


class TestIntentForgeFieldRejection:
    def test_author_field_rejected(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "hi", "author": "system"},
        )
        assert r.status_code == 422

    def test_id_field_rejected(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "hi", "id": "evt_evil"},
        )
        assert r.status_code == 422

    def test_timestamp_field_rejected(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "hi", "timestamp": 0},
        )
        assert r.status_code == 422

    def test_agent_id_field_rejected(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "hi", "agent_id": "agent:foo"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# §4.3  Off-allowlist type rejected (discriminating)
# ---------------------------------------------------------------------------


class TestIntentTypeAllowlist:
    def test_state_transition_rejected(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "state_transition", "content": "hack"},
        )
        assert r.status_code == 422

    def test_utterance_rejected(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "utterance", "content": "agent says hi"},
        )
        assert r.status_code == 422

    def test_autonomy_decision_rejected(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "autonomy_decision", "content": "hack"},
        )
        assert r.status_code == 422

    def test_tool_call_rejected(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "tool_call", "content": "hack"},
        )
        assert r.status_code == 422

    def test_user_input_allowed(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "valid"},
        )
        assert r.status_code == 200

    def test_retraction_allowed(self, client: TestClient, ctx: AppContext) -> None:
        room_id = _post_room(client)
        # First append an event to retract
        evt = Event(
            id=generate_event_id(),
            room_id=RoomId(room_id),
            type=EventType.USER_INPUT,
            author="user",
            timestamp=now_ms(),
            content="original",
        )
        ctx.writer_store.append(evt)

        r = client.post(
            f"/rooms/{room_id}/intent",
            json={
                "type": "retraction",
                "content": "retract",
                "metadata": {"retracts": evt.id, "reason": "mistake"},
            },
        )
        assert r.status_code == 200
        assert r.json()["appended_event"]["type"] == "retraction"


# ---------------------------------------------------------------------------
# §4.4  Typed-metadata violation rejected (discriminating)
# ---------------------------------------------------------------------------


class TestIntentMetadataValidation:
    def test_decision_without_required_fields_rejected(self, client: TestClient) -> None:
        room_id = _post_room(client)
        # DECISION requires based_on (min_length=1)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "decision", "content": "decide", "metadata": {}},
        )
        assert r.status_code == 422

    def test_decision_with_valid_metadata_allowed(
        self, client: TestClient, ctx: AppContext
    ) -> None:
        room_id = _post_room(client)
        # Append an event to reference in based_on
        ref_evt = Event(
            id=generate_event_id(),
            room_id=RoomId(room_id),
            type=EventType.USER_INPUT,
            author="user",
            timestamp=now_ms(),
            content="reference",
        )
        ctx.writer_store.append(ref_evt)

        r = client.post(
            f"/rooms/{room_id}/intent",
            json={
                "type": "decision",
                "content": "decided",
                "metadata": {"based_on": [ref_evt.id]},
            },
        )
        assert r.status_code == 200
        assert r.json()["appended_event"]["type"] == "decision"

    def test_retraction_without_retracts_rejected(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={
                "type": "retraction",
                "content": "retract",
                "metadata": {"reason": "no retracts field"},
            },
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# §4.5  Authority check: DECISION{promotion:true} appends but does NOT promote
# (ADR-025 D4a / arch-Y1 / ADR-016 D10)
# ---------------------------------------------------------------------------


class TestDecisionPromotionAuthority:
    def test_decision_promotion_true_appends_but_no_vk_created(
        self, client: TestClient, ctx: AppContext
    ) -> None:
        """A client-posted DECISION{promotion:true} via /intent+run_turn cannot
        reach the durable-memory promotion path (ADR-016 D10: run_turn does NOT
        call promote_hypothesis on a bare DECISION event).

        Acceptance: event appended, turn result has no exception, store is clean.
        """
        room_id = _post_room(client)
        # Append a reference event for based_on
        ref_evt = Event(
            id=generate_event_id(),
            room_id=RoomId(room_id),
            type=EventType.USER_INPUT,
            author="user",
            timestamp=now_ms(),
            content="hypothesis",
        )
        ctx.writer_store.append(ref_evt)

        fake_hyp_id = "hyp_" + uuid.uuid4().hex
        fake_vk_id = "vk_" + uuid.uuid4().hex

        r = client.post(
            f"/rooms/{room_id}/intent",
            json={
                "type": "decision",
                "content": "promote this",
                "metadata": {
                    "based_on": [ref_evt.id],
                    "promotion": True,
                    "hypothesis_id": fake_hyp_id,
                    "vk_id": fake_vk_id,
                    "user_id": "test_user",
                },
            },
        )
        # Event was appended (not rejected)
        assert r.status_code == 200
        evt = r.json()["appended_event"]
        assert evt["type"] == "decision"
        assert evt["author"] == "user"
        # metadata stored as posted (shape-valid)
        assert evt["metadata"]["promotion"] is True

        # Turn result returned normally — no exception from run_turn
        turn = r.json()["turn"]
        assert "utterances" in turn
        # No VK was created (run_turn does not call promote_hypothesis)
        # Verify via absence of any VK-related events in the store
        events = client.get(f"/rooms/{room_id}/events").json()
        event_types = [e["type"] for e in events]
        # Only user_input (ref) + decision; no hypothesis/vk promotion chain
        assert "decision" in event_types
        assert "autonomy_decision" not in event_types


# ---------------------------------------------------------------------------
# §4.6  Nonexistent room returns append-stage error
# ---------------------------------------------------------------------------


class TestIntentRoomNotFound:
    def test_nonexistent_room_returns_intent_error_append_stage(self, client: TestClient) -> None:
        fake_room = "room_" + "0" * 32
        r = client.post(
            f"/rooms/{fake_room}/intent",
            json={"type": "user_input", "content": "hi"},
        )
        assert r.status_code == 422
        body = r.json()
        assert body["stage"] == "append"
        assert body["appended_event_id"] is None


# ---------------------------------------------------------------------------
# §1 write e2e: POST intent → events stream to WS subscriber
# ---------------------------------------------------------------------------


class TestIntentE2EStream:
    def test_intent_events_stream_to_ws_subscriber(self, client: TestClient) -> None:
        """POST /intent → user event appended → event streams to connected WS subscriber."""
        room_id = _post_room(client)
        received_live: list[dict[str, Any]] = []
        ws_ready = threading.Event()
        ws_errors: list[Exception] = []

        def _ws_collect() -> None:
            try:
                with client.websocket_connect(f"/rooms/{room_id}/stream") as ws:
                    # Drain replay (empty room)
                    while True:
                        msg = ws.receive_json()
                        if msg["kind"] == "replay_complete":
                            break
                    ws_ready.set()
                    # Receive live event from the intent
                    msg = ws.receive_json()
                    received_live.append(msg)
            except Exception as exc:
                ws_errors.append(exc)

        ws_thread = threading.Thread(target=_ws_collect)
        ws_thread.start()

        ws_ready.wait(timeout=5)
        assert ws_ready.is_set(), "WS subscriber did not connect in time"

        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "hello world"},
        )
        assert r.status_code == 200
        appended_id = r.json()["appended_event"]["id"]

        ws_thread.join(timeout=8)
        assert not ws_thread.is_alive(), "WS thread timed out — event not received in 8s"
        assert not ws_errors, f"WS errors: {ws_errors}"
        assert len(received_live) >= 1, "Expected at least 1 live event"
        # The user_event must be in the live stream
        live_ids = [m["event"]["id"] for m in received_live if m["kind"] == "event"]
        assert appended_id in live_ids, (
            f"user_event {appended_id!r} not found in live stream. Got: {live_ids}"
        )

    def test_intent_live_event_has_correct_author_and_type(self, client: TestClient) -> None:
        """Discriminating: the streamed event has author='user' and correct type."""
        room_id = _post_room(client)
        received: list[dict[str, Any]] = []
        ws_ready = threading.Event()

        def _ws_collect() -> None:
            try:
                with client.websocket_connect(f"/rooms/{room_id}/stream") as ws:
                    while True:
                        msg = ws.receive_json()
                        if msg["kind"] == "replay_complete":
                            break
                    ws_ready.set()
                    msg = ws.receive_json()
                    received.append(msg)
            except Exception:
                pass

        t = threading.Thread(target=_ws_collect)
        t.start()
        ws_ready.wait(timeout=5)

        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "discriminate me"},
        )
        assert r.status_code == 200
        t.join(timeout=8)

        assert received, "No live event received"
        user_events = [
            m for m in received if m["kind"] == "event" and m["event"]["type"] == "user_input"
        ]
        assert user_events, "No user_input event in live stream"
        assert user_events[0]["event"]["author"] == "user"
        assert user_events[0]["event"]["content"] == "discriminate me"
