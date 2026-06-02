"""§1 read e2e — HTTP read surface over the event store.

Covers: create room, GET room/events/snapshot/thread, 404 paths.
Events are appended directly to ctx.writer_store for setup (the API has
no "append event" endpoint — that flows through POST /intent in P3.2-4).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from orchestrator.core.event import (
    Event,
    EventType,
    generate_event_id,
    generate_room_id,
    now_ms,
)

# ---------------------------------------------------------------------------
# §1.1  POST /rooms — room creation
# ---------------------------------------------------------------------------


class TestCreateRoom:
    def test_create_room_returns_201_and_room(self, client: TestClient) -> None:
        r = client.post("/rooms", json={"type": "free_chat"})
        assert r.status_code == 201
        data = r.json()
        assert data["type"] == "free_chat"
        assert data["id"].startswith("room_")

    def test_create_room_unknown_type_rejected(self, client: TestClient) -> None:
        r = client.post("/rooms", json={"type": "not_a_type"})
        assert r.status_code == 422

    def test_create_room_extra_field_rejected(self, client: TestClient) -> None:
        r = client.post("/rooms", json={"type": "free_chat", "extra": "bad"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# §1.2  GET /rooms/{id} — fetch room
# ---------------------------------------------------------------------------


class TestGetRoom:
    def test_get_existing_room(self, client: TestClient) -> None:
        create = client.post("/rooms", json={"type": "research"})
        room_id = create.json()["id"]

        r = client.get(f"/rooms/{room_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == room_id
        assert data["type"] == "research"

    def test_get_nonexistent_room_404(self, client: TestClient) -> None:
        r = client.get(f"/rooms/{generate_room_id()}")
        assert r.status_code == 404

    def test_get_room_has_created_at(self, client: TestClient) -> None:
        create = client.post("/rooms", json={"type": "bug_fix"})
        room_id = create.json()["id"]
        r = client.get(f"/rooms/{room_id}")
        data = r.json()
        assert isinstance(data["created_at"], int)
        assert data["created_at"] > 0


# ---------------------------------------------------------------------------
# §1.3  GET /rooms/{id}/events — fetch events
# ---------------------------------------------------------------------------


class TestGetRoomEvents:
    def test_empty_room_returns_empty_list(self, client: TestClient) -> None:
        create = client.post("/rooms", json={"type": "free_chat"})
        room_id = create.json()["id"]

        r = client.get(f"/rooms/{room_id}/events")
        assert r.status_code == 200
        assert r.json() == []

    def test_events_returned_in_order(
        self,
        client: TestClient,
        ctx: object,
    ) -> None:
        from orchestrator.api.app import AppContext
        from orchestrator.core.event import RoomId, TimestampMs

        assert isinstance(ctx, AppContext)
        create = client.post("/rooms", json={"type": "free_chat"})
        room_id_str = create.json()["id"]
        rid = RoomId(room_id_str)

        base = now_ms()
        for i in range(3):
            evt = Event(
                id=generate_event_id(),
                room_id=rid,
                type=EventType.USER_INPUT,
                author="user",
                timestamp=TimestampMs(base + i),
                content=f"msg {i}",
            )
            ctx.writer_store.append(evt)

        r = client.get(f"/rooms/{room_id_str}/events")
        assert r.status_code == 200
        events = r.json()
        assert len(events) == 3
        contents = [e["content"] for e in events]
        assert contents == ["msg 0", "msg 1", "msg 2"]

    def test_nonexistent_room_returns_empty_list(self, client: TestClient) -> None:
        r = client.get(f"/rooms/{generate_room_id()}/events")
        assert r.status_code == 200
        assert r.json() == []


# ---------------------------------------------------------------------------
# §1.4  GET /rooms/{id}/snapshot — produce snapshot
# ---------------------------------------------------------------------------


class TestGetSnapshot:
    def test_snapshot_of_empty_room(self, client: TestClient) -> None:
        create = client.post("/rooms", json={"type": "idea_validation"})
        room_id = create.json()["id"]

        r = client.get(f"/rooms/{room_id}/snapshot")
        assert r.status_code == 200
        data = r.json()
        assert data["room_id"] == room_id
        assert data["event_count"] == 0
        assert data["room_type"] == "idea_validation"

    def test_snapshot_nonexistent_room_404(self, client: TestClient) -> None:
        r = client.get(f"/rooms/{generate_room_id()}/snapshot")
        assert r.status_code == 404

    def test_snapshot_includes_event_count(self, client: TestClient, ctx: object) -> None:
        from orchestrator.api.app import AppContext
        from orchestrator.core.event import RoomId, TimestampMs

        assert isinstance(ctx, AppContext)
        create = client.post("/rooms", json={"type": "free_chat"})
        room_id_str = create.json()["id"]
        rid = RoomId(room_id_str)

        evt = Event(
            id=generate_event_id(),
            room_id=rid,
            type=EventType.USER_INPUT,
            author="user",
            timestamp=TimestampMs(now_ms()),
            content="hello",
        )
        ctx.writer_store.append(evt)

        r = client.get(f"/rooms/{room_id_str}/snapshot")
        assert r.status_code == 200
        assert r.json()["event_count"] == 1


# ---------------------------------------------------------------------------
# §1.5  GET /events/{id}/thread — fetch thread
# ---------------------------------------------------------------------------


class TestGetThread:
    def test_thread_of_single_event(self, client: TestClient, ctx: object) -> None:
        from orchestrator.api.app import AppContext
        from orchestrator.core.event import RoomId, TimestampMs

        assert isinstance(ctx, AppContext)
        create = client.post("/rooms", json={"type": "free_chat"})
        room_id_str = create.json()["id"]
        rid = RoomId(room_id_str)

        evt = Event(
            id=generate_event_id(),
            room_id=rid,
            type=EventType.USER_INPUT,
            author="user",
            timestamp=TimestampMs(now_ms()),
            content="root",
        )
        ctx.writer_store.append(evt)

        r = client.get(f"/events/{evt.id}/thread")
        assert r.status_code == 200
        thread = r.json()
        assert len(thread) == 1
        assert thread[0]["id"] == evt.id

    def test_thread_walks_parent_chain(self, client: TestClient, ctx: object) -> None:
        from orchestrator.api.app import AppContext
        from orchestrator.core.event import RoomId, TimestampMs

        assert isinstance(ctx, AppContext)
        create = client.post("/rooms", json={"type": "free_chat"})
        room_id_str = create.json()["id"]
        rid = RoomId(room_id_str)

        base = now_ms()
        root = Event(
            id=generate_event_id(),
            room_id=rid,
            type=EventType.USER_INPUT,
            author="user",
            timestamp=base,
            content="root",
        )
        ctx.writer_store.append(root)

        child = Event(
            id=generate_event_id(),
            parent_id=root.id,
            room_id=rid,
            type=EventType.UTTERANCE,
            author="agent:bot",
            timestamp=TimestampMs(base + 1),
            content="reply",
        )
        ctx.writer_store.append(child)

        r = client.get(f"/events/{child.id}/thread")
        assert r.status_code == 200
        thread = r.json()
        assert len(thread) == 2
        assert thread[0]["id"] == root.id
        assert thread[1]["id"] == child.id

    def test_nonexistent_event_404(self, client: TestClient) -> None:
        r = client.get(f"/events/{generate_event_id()}/thread")
        assert r.status_code == 404
