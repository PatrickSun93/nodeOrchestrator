"""§2 concurrency — WS live stream, subscribe-then-replay+dedup, liveness.

Covers:
  - WS replay: subscriber sees all historical events + replay_complete sentinel
  - subscribe-then-replay+dedup: no gap or duplicate events in delivery
  - read-during-turn liveness: GET does not block while writer executor busy
  - slow subscriber dropped without stalling the bus or other subscribers
  - Multiple WS connections to same room work independently
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.api.app import AppContext
from orchestrator.api.pubsub import _QUEUE_MAX_SIZE, RoomEventBus
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    TimestampMs,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.room import Room, RoomType
from tests.api.conftest import make_auth_headers

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_room(client: TestClient, room_type: str = "free_chat") -> str:
    r = client.post("/rooms", json={"type": room_type})
    assert r.status_code == 201
    result: str = r.json()["id"]
    return result


def _append_event(ctx: AppContext, room_id: str, content: str = "hi", offset_ms: int = 0) -> Event:
    rid = RoomId(room_id)
    evt = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.USER_INPUT,
        author="user",
        timestamp=TimestampMs(now_ms() + offset_ms),
        content=content,
    )
    ctx.writer_store.append(evt)
    return evt


def _drain_until_replay_complete(ws: Any) -> list[dict[str, Any]]:
    """Drain a WS until replay_complete; return all event messages."""
    events = []
    while True:
        msg = ws.receive_json()
        if msg["kind"] == "replay_complete":
            break
        if msg["kind"] == "event":
            events.append(msg)
    return events


# ---------------------------------------------------------------------------
# §2.1  WS replay: subscriber sees historical events + replay_complete
# ---------------------------------------------------------------------------


class TestWsReplay:
    def test_empty_room_replay_complete_immediately(self, client: TestClient) -> None:
        room_id = _post_room(client)
        with client.websocket_connect(f"/rooms/{room_id}/stream") as ws:
            msg = ws.receive_json()
        assert msg["kind"] == "replay_complete"

    def test_replay_returns_all_historical_events_in_order(
        self, client: TestClient, ctx: AppContext
    ) -> None:
        room_id = _post_room(client)
        for i in range(4):
            _append_event(ctx, room_id, f"event-{i}", i)

        with client.websocket_connect(f"/rooms/{room_id}/stream") as ws:
            replayed = _drain_until_replay_complete(ws)

        assert len(replayed) == 4
        replayed_contents = [e["event"]["content"] for e in replayed]
        assert replayed_contents == [f"event-{i}" for i in range(4)]

    def test_replay_ids_match_appended_events(self, client: TestClient, ctx: AppContext) -> None:
        room_id = _post_room(client)
        appended = [_append_event(ctx, room_id, f"msg-{i}", i) for i in range(3)]

        with client.websocket_connect(f"/rooms/{room_id}/stream") as ws:
            replayed = _drain_until_replay_complete(ws)

        replayed_ids = [e["event"]["id"] for e in replayed]
        assert replayed_ids == [e.id for e in appended]


# ---------------------------------------------------------------------------
# §2.2  Multiple WS connections to the same room work independently
# ---------------------------------------------------------------------------


class TestMultipleConnections:
    def test_two_concurrent_subscribers_both_see_replay(
        self, app: FastAPI, ctx: AppContext
    ) -> None:
        room_id_str = generate_room_id()
        room = Room(id=RoomId(room_id_str), type=RoomType.FREE_CHAT)
        ctx.writer_store.append_room(room)
        pre = [_append_event(ctx, room_id_str, f"pre-{i}", i) for i in range(3)]

        results: list[list[dict[str, Any]]] = [[], []]
        errors: list[Exception] = []

        auth_hdrs = make_auth_headers(ctx)

        def _collect(idx: int) -> None:
            try:
                with TestClient(app, headers=auth_hdrs).websocket_connect(
                    f"/rooms/{room_id_str}/stream"
                ) as ws:
                    collected: list[dict[str, Any]] = []
                    for _ in range(len(pre) + 5):
                        msg = ws.receive_json()
                        if msg["kind"] == "replay_complete":
                            break
                        if msg["kind"] == "event":
                            collected.append(msg)
                    results[idx] = collected
            except Exception as exc:
                errors.append(exc)

        # daemon=True: CI safety net only — with per-thread reader connections
        # (RW7) replay_complete arrives promptly; threads should never hit timeout.
        threads = [threading.Thread(target=_collect, args=(i,), daemon=True) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not any(t.is_alive() for t in threads), "Subscriber threads timed out — reader hang?"
        assert not errors, f"WS errors: {errors}"
        for i in range(2):
            assert len(results[i]) == 3
            assert [e["event"]["id"] for e in results[i]] == [e.id for e in pre]

    def test_subscriber_unsubscribed_on_disconnect(
        self, client: TestClient, ctx: AppContext
    ) -> None:
        room_id = _post_room(client)
        rid = RoomId(room_id)

        with client.websocket_connect(f"/rooms/{room_id}/stream") as ws:
            _drain_until_replay_complete(ws)
            subs_during = len(ctx.bus._subscribers.get(rid, []))

        subs_after = len(ctx.bus._subscribers.get(rid, []))
        assert subs_during == 1, f"Expected 1 subscriber during, got {subs_during}"
        assert subs_after == 0, f"Expected 0 subscribers after disconnect, got {subs_after}"


# ---------------------------------------------------------------------------
# §2.3  Subscribe-then-replay+dedup — no duplicate event ids
# ---------------------------------------------------------------------------


class TestReplayDedup:
    def test_no_duplicate_ids_in_replay(self, client: TestClient, ctx: AppContext) -> None:
        """All event ids in the replay phase must be unique."""
        room_id = _post_room(client)
        for i in range(5):
            _append_event(ctx, room_id, f"msg-{i}", i)

        with client.websocket_connect(f"/rooms/{room_id}/stream") as ws:
            seen: list[str] = []
            while True:
                msg = ws.receive_json()
                if msg["kind"] == "replay_complete":
                    break
                if msg["kind"] == "event":
                    seen.append(msg["event"]["id"])

        assert len(seen) == len(set(seen)), "Duplicate event ids in replay"
        assert len(seen) == 5


# ---------------------------------------------------------------------------
# §2.4  Read-during-turn liveness: GET does NOT block behind writer executor
# ---------------------------------------------------------------------------


class TestReadLiveness:
    def test_get_events_not_blocked_while_writer_busy(
        self, client: TestClient, ctx: AppContext
    ) -> None:
        room_id = _post_room(client)
        barrier = threading.Event()
        writer_released = threading.Event()

        def _slow_write() -> None:
            def _block() -> None:
                barrier.set()
                time.sleep(0.3)
                writer_released.set()

            ctx.writer_executor.submit(_block).result()

        write_thread = threading.Thread(target=_slow_write)
        write_thread.start()

        barrier.wait(timeout=2)
        assert barrier.is_set(), "Writer executor not occupied"

        start = time.monotonic()
        r = client.get(f"/rooms/{room_id}/events")
        elapsed = time.monotonic() - start

        assert r.status_code == 200
        assert elapsed < 0.25, f"GET blocked {elapsed:.3f}s while writer busy (expected <0.25s)"

        write_thread.join(timeout=2)

    def test_snapshot_not_blocked_while_writer_busy(
        self, client: TestClient, ctx: AppContext
    ) -> None:
        room_id = _post_room(client)
        barrier = threading.Event()

        def _slow_write() -> None:
            def _block() -> None:
                barrier.set()
                time.sleep(0.3)

            ctx.writer_executor.submit(_block).result()

        write_thread = threading.Thread(target=_slow_write)
        write_thread.start()
        barrier.wait(timeout=2)

        start = time.monotonic()
        r = client.get(f"/rooms/{room_id}/snapshot")
        elapsed = time.monotonic() - start

        assert r.status_code == 200
        assert elapsed < 0.25

        write_thread.join(timeout=2)


# ---------------------------------------------------------------------------
# §2.5  Slow subscriber drop — bus unit test
# ---------------------------------------------------------------------------


class TestSlowSubscriberDrop:
    def test_full_queue_subscriber_dropped_silently(self) -> None:
        """A subscriber whose queue fills gets dropped; other subs are unaffected."""
        import asyncio

        bus = RoomEventBus()
        room_id = RoomId(generate_room_id())

        async def _run() -> None:
            q_slow: asyncio.Queue[Event] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
            q_fast: asyncio.Queue[Event] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)

            bus._subscribers[room_id] = [q_slow, q_fast]

            # Fill q_slow to capacity
            for _ in range(_QUEUE_MAX_SIZE):
                e = Event(
                    id=generate_event_id(),
                    room_id=room_id,
                    type=EventType.USER_INPUT,
                    author="user",
                    timestamp=now_ms(),
                    content="fill",
                )
                q_slow.put_nowait(e)

            assert q_slow.full()

            # Publish one more event
            overflow = Event(
                id=generate_event_id(),
                room_id=room_id,
                type=EventType.USER_INPUT,
                author="user",
                timestamp=now_ms(),
                content="overflow",
            )
            bus.publish(room_id, [overflow])

            # q_slow was dropped; q_fast received the event
            assert not q_slow.full() or q_slow.maxsize == _QUEUE_MAX_SIZE
            # q_fast received overflow
            assert q_fast.get_nowait().id == overflow.id
            # q_slow no longer subscribed
            assert q_slow not in bus._subscribers.get(room_id, [])

        asyncio.run(_run())

    def test_dropped_subscriber_does_not_block_others(self) -> None:
        """Dropping a slow subscriber must not prevent other subscribers from receiving."""
        import asyncio

        bus = RoomEventBus()
        room_id = RoomId(generate_room_id())

        async def _run() -> None:
            q_slow: asyncio.Queue[Event] = asyncio.Queue(maxsize=1)
            q_fast: asyncio.Queue[Event] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
            bus._subscribers[room_id] = [q_slow, q_fast]

            # Fill q_slow
            fill = Event(
                id=generate_event_id(),
                room_id=room_id,
                type=EventType.USER_INPUT,
                author="user",
                timestamp=now_ms(),
                content="fill",
            )
            q_slow.put_nowait(fill)

            # Publish 3 events — q_slow drops on first, q_fast gets all
            delivered: list[Event] = []
            for i in range(3):
                e = Event(
                    id=generate_event_id(),
                    room_id=room_id,
                    type=EventType.USER_INPUT,
                    author="user",
                    timestamp=TimestampMs(now_ms() + i),
                    content=f"live-{i}",
                )
                delivered.append(e)
            bus.publish(room_id, delivered)

            # q_fast received all 3
            received = [q_fast.get_nowait() for _ in range(q_fast.qsize())]
            assert [e.id for e in received] == [e.id for e in delivered]

        asyncio.run(_run())
