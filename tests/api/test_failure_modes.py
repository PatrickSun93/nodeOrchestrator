"""§3 failure modes — partial-turn error envelope, payload validation, WS disconnect.

Covers (ADR-025 D5, R0-B Y3):
  - append-fail (invalid parent_id) → IntentError{stage:"append", appended_event_id:None}
  - run_turn-raise → IntentError{stage:"turn", appended_event_id:<id>}, store consistent
  - malformed payload (missing required fields) → 422, no append
  - oversized payload (>64 KiB) → 422, no append
  - WS disconnect → turn completion unaffected (writer not blocked by subscriber state)
  - check_same_thread=False: concurrent reader-executor queries do not crash
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from orchestrator.api.app import AppContext
from orchestrator.core.event import RoomId
from tests.api.conftest import TEST_USER_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_room(client: TestClient, room_type: str = "free_chat") -> str:
    r = client.post("/rooms", json={"type": room_type})
    assert r.status_code == 201
    result: str = r.json()["id"]
    return result


def _drain_replay(ws: Any) -> None:
    while True:
        msg = ws.receive_json()
        if msg["kind"] == "replay_complete":
            break


# ---------------------------------------------------------------------------
# §3.1  Append-fail (invalid parent_id) → stage="append", appended_event_id=None
# ---------------------------------------------------------------------------


class TestAppendFailStage:
    def test_invalid_parent_id_returns_422_append_stage(self, client: TestClient) -> None:
        """parent_id that does not exist → InvalidParentError → append-fail envelope."""
        room_id = _post_room(client)
        fake_parent = "evt_" + "0" * 32

        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "hi", "parent_id": fake_parent},
        )
        assert r.status_code == 422
        body = r.json()
        assert body["stage"] == "append"
        assert body["appended_event_id"] is None

    def test_invalid_parent_id_leaves_store_empty(self, client: TestClient) -> None:
        """No events appended when append fails (safe to retry)."""
        room_id = _post_room(client)
        fake_parent = "evt_" + "0" * 32

        client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "fail me", "parent_id": fake_parent},
        )
        events = client.get(f"/rooms/{room_id}/events").json()
        assert events == [], "No events should be in the store after append-fail"


# ---------------------------------------------------------------------------
# §3.2  run_turn-raise → stage="turn", appended_event_id=<id>, store consistent
# ---------------------------------------------------------------------------


class TestTurnFailStage:
    def test_run_turn_raise_returns_500_turn_stage(self, client: TestClient) -> None:
        """run_turn raises → 500 IntentError{stage:'turn'} with appended_event_id set."""
        room_id = _post_room(client)

        with patch(
            "orchestrator.rooms.runtime.run_turn",
            side_effect=RuntimeError("simulated LLM failure"),
        ):
            r = client.post(
                f"/rooms/{room_id}/intent",
                json={"type": "user_input", "content": "fail turn"},
            )

        assert r.status_code == 500
        body = r.json()
        assert body["stage"] == "turn"
        assert body["appended_event_id"] is not None, "Intent was appended before turn raised"
        assert "simulated LLM failure" in body["reason"]

    def test_run_turn_raise_intent_persisted_in_store(self, client: TestClient) -> None:
        """After turn-fail, the user event IS in the store (intent persisted, no re-post)."""
        room_id = _post_room(client)

        with patch(
            "orchestrator.rooms.runtime.run_turn",
            side_effect=RuntimeError("fail"),
        ):
            r = client.post(
                f"/rooms/{room_id}/intent",
                json={"type": "user_input", "content": "persist me"},
            )

        assert r.status_code == 500
        appended_event_id = r.json()["appended_event_id"]

        events = client.get(f"/rooms/{room_id}/events").json()
        assert len(events) == 1, "Exactly the user event should be in the store"
        assert events[0]["id"] == appended_event_id
        assert events[0]["author"] == f"user:{TEST_USER_ID}"  # P4.5-4 CLASS A
        assert events[0]["content"] == "persist me"

    def test_run_turn_raise_no_partial_writes_surfaced(self, client: TestClient) -> None:
        """After turn-fail, only the user event is in the store (no partial turn state)."""
        room_id = _post_room(client)

        with patch(
            "orchestrator.rooms.runtime.run_turn",
            side_effect=RuntimeError("fail partway"),
        ):
            client.post(
                f"/rooms/{room_id}/intent",
                json={"type": "user_input", "content": "check partial"},
            )

        events = client.get(f"/rooms/{room_id}/events").json()
        event_types = [e["type"] for e in events]
        # Only user_input; no state_transition or utterance from a partial turn
        assert all(t == "user_input" for t in event_types), (
            f"Unexpected event types in store after turn-fail: {event_types}"
        )


# ---------------------------------------------------------------------------
# §3.3  Malformed payload → 422, no append
# ---------------------------------------------------------------------------


class TestMalformedPayload:
    def test_missing_type_returns_422(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(f"/rooms/{room_id}/intent", json={"content": "hi"})
        assert r.status_code == 422

    def test_missing_content_returns_422(self, client: TestClient) -> None:
        room_id = _post_room(client)
        r = client.post(f"/rooms/{room_id}/intent", json={"type": "user_input"})
        assert r.status_code == 422

    def test_malformed_payload_leaves_store_empty(self, client: TestClient) -> None:
        room_id = _post_room(client)
        client.post(f"/rooms/{room_id}/intent", json={"content": "no type"})
        events = client.get(f"/rooms/{room_id}/events").json()
        assert events == []


# ---------------------------------------------------------------------------
# §3.4  Oversized payload → 422, no append (ADR-025 D7 trust boundary)
# ---------------------------------------------------------------------------


class TestOversizedPayload:
    def test_oversized_body_returns_422(self, client: TestClient) -> None:
        room_id = _post_room(client)
        large_content = "x" * 70_000  # > 64 KiB limit
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": large_content},
        )
        assert r.status_code == 422

    def test_oversized_body_leaves_store_empty(self, client: TestClient) -> None:
        room_id = _post_room(client)
        large_content = "x" * 70_000
        client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": large_content},
        )
        events = client.get(f"/rooms/{room_id}/events").json()
        assert events == []


# ---------------------------------------------------------------------------
# §3.5  WS disconnect → turn completion unaffected (writer not blocked by subscriber)
# ---------------------------------------------------------------------------


class TestWsDisconnectTurnUnaffected:
    def test_intent_succeeds_after_ws_disconnect(self, client: TestClient, ctx: AppContext) -> None:
        """POST /intent returns 200 after the WS subscriber disconnects."""
        room_id = _post_room(client)

        with client.websocket_connect(f"/rooms/{room_id}/stream") as ws:
            _drain_replay(ws)
        # WS now disconnected

        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "still works"},
        )
        assert r.status_code == 200
        assert r.json()["appended_event"]["author"] == f"user:{TEST_USER_ID}"  # P4.5-4 CLASS A

    def test_intent_event_in_store_after_ws_disconnect(
        self, client: TestClient, ctx: AppContext
    ) -> None:
        """Event persists normally even when no WS subscribers are connected."""
        room_id = _post_room(client)

        with client.websocket_connect(f"/rooms/{room_id}/stream") as ws:
            _drain_replay(ws)

        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "persist without ws"},
        )
        assert r.status_code == 200
        appended_id = r.json()["appended_event"]["id"]

        events = client.get(f"/rooms/{room_id}/events").json()
        assert any(e["id"] == appended_id for e in events)

    def test_publish_to_disconnected_subscriber_does_not_block_writer(
        self, client: TestClient, ctx: AppContext
    ) -> None:
        """Verify no exception or deadlock when intent is published but subscriber already gone."""
        room_id = _post_room(client)
        ws_ready = threading.Event()
        ws_done = threading.Event()

        def _ws_thread() -> None:
            with client.websocket_connect(f"/rooms/{room_id}/stream") as ws:
                _drain_replay(ws)
                ws_ready.set()
            ws_done.set()

        t = threading.Thread(target=_ws_thread)
        t.start()
        ws_ready.wait(timeout=5)
        assert ws_ready.is_set()

        # Wait for WS to fully close so subscriber is removed
        ws_done.wait(timeout=5)
        assert ws_done.is_set()

        # POST intent: publisher calls bus.publish with no subscribers → no error
        r = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "no subscriber"},
        )
        assert r.status_code == 200

        t.join(timeout=2)


# ---------------------------------------------------------------------------
# §3.6  check_same_thread=False — reader connection usable from executor threads
# ---------------------------------------------------------------------------


class TestConcurrentReaderNoThreadError:
    def test_reader_executor_cross_thread_no_check_same_thread_error(
        self, client: TestClient, ctx: AppContext
    ) -> None:
        """Reader conn (check_same_thread=False) works from the reader executor's threads.

        The connection is created in the fixture (test-setup thread).
        The reader_executor runs on different threads.
        check_same_thread=False must allow this cross-thread access.
        """
        room_id = _post_room(client)

        errors: list[Exception] = []

        def _read_in_executor() -> None:
            try:
                # Direct reader_store access from an executor thread
                ctx.reader_store.get_room_events(RoomId(room_id))
            except Exception as exc:
                errors.append(exc)

        # Submit to the reader executor — runs in a different thread than the test thread.
        # With check_same_thread=False this must not raise ProgrammingError.
        future = ctx.reader_executor.submit(_read_in_executor)
        future.result(timeout=5)

        assert not errors, f"Reader cross-thread access raised: {errors}"

    def test_reader_not_blocked_while_writer_busy(
        self, client: TestClient, ctx: AppContext
    ) -> None:
        """GET /events returns promptly even while the writer executor is occupied.

        Confirms WAL-mode + separate read conn; reader_executor != writer_executor.
        """
        import time

        room_id = _post_room(client)
        barrier = threading.Event()

        def _occupy_writer() -> None:
            def _block() -> None:
                barrier.set()
                time.sleep(0.25)

            ctx.writer_executor.submit(_block).result()

        writer_thread = threading.Thread(target=_occupy_writer)
        writer_thread.start()
        barrier.wait(timeout=2)
        assert barrier.is_set(), "Writer executor not occupied"

        start = time.monotonic()
        r = client.get(f"/rooms/{room_id}/events")
        elapsed = time.monotonic() - start

        assert r.status_code == 200
        assert elapsed < 0.20, f"GET blocked {elapsed:.3f}s — reader is not separate from writer"

        writer_thread.join(timeout=2)
