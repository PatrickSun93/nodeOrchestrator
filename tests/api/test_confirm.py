"""B3 acceptance tests for POST /rooms/{room_id}/confirm (ADR-030 D3/D5).

Coverage:
  §1 Happy path: approve → TOOL_CALL appended (from record) → executor → TOOL_RESULT
  §2 Idempotency: double-approve → already_resolved (single TOOL_CALL/TOOL_RESULT)
  §3 Cancel: TOOL_CALL_CANCELLED appended, no TOOL_CALL, no execution
  §4 Room-state gate (Y3): closed room → stage:append reason:room_closed
  §5 No-forge / backend-authoritative: extra fields → 422; wrong pending_event_id → fail closed
  §6 Cross-turn call_id collision (Y2): prior-turn result does not false-reject fresh pending
  §7 Writer-executor atomicity (N3): confirm closure runs on writer_executor
  §8 Pending-resolution consistency (R0-A Y1): snapshot pending ⟺ endpoint still-pending
  §9 Execute-stage failure (R0-A Y2, ADR-030 D5): TOOL_CALL durable; re-confirm already_resolved
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.api.app import AppContext, _make_test_app
from orchestrator.api.auth.session import create_token
from orchestrator.api.auth.users import create_user, init_auth_schema
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    ToolCallPendingMeta,
    ToolResultMeta,
    build_author,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.derived.snapshot import produce_snapshot
from orchestrator.llm.types import (
    LLMResponse,
    ModelId,
    ProviderId,
    RequestId,
    Usage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_router() -> MagicMock:
    router = MagicMock(spec=LLMRouterProtocol)
    response = LLMResponse(
        request_id=RequestId(generate_event_id()),
        content="agent reply",
        tool_calls=[],
        model_id_requested=ModelId("mock-model"),
        model_id_used=ModelId("mock-model"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=1, output_tokens=1, cost_usd=None),
        latency_ms=0,
        finish_reason="stop",
    )
    router.call.return_value = response
    return router


_TEST_USER = "testuser"
_TEST_PW = "test-pw"


def _make_store(db_path: Any) -> EventStore:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    store = EventStore(conn)
    store.init_schema()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    # Auth tables alongside event tables (ADR-039 D2)
    init_auth_schema(conn)
    create_user(conn, _TEST_USER, _TEST_PW)
    return store


def _auth_headers(ctx: AppContext) -> dict[str, str]:
    raw_token = create_token(ctx.writer_store.conn, _TEST_USER)
    return {"Authorization": f"Bearer {raw_token}"}


def _make_ctx(db_path: Any, local_tools: dict[str, Any] | None = None) -> AppContext:
    writer_store = _make_store(db_path)
    reader_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    reader_store = EventStore(reader_conn)
    return AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-writer"),
        reader_executor=ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-reader"),
        bus=RoomEventBus(),
        available_agents={},
        available_skills={},
        regex_registry={},
        tools={},
        llm_router=_mock_router(),
        local_tools=local_tools or {},
    )


def _make_room(store: EventStore, state: str = "setup") -> RoomId:
    rid = generate_room_id()
    store.append_room(Room(id=rid, type=RoomType.FREE_CHAT, state=state))
    return rid


def _append_pending(
    store: EventStore,
    room_id: RoomId,
    *,
    call_id: str = "call_abc",
    tool_name: str = "apply_edit",
    tier: str = "countdown_confirm",
    agent_id: str = "operator",
) -> Event:
    """Append a TOOL_CALL_PENDING event and return it."""
    evt = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_CALL_PENDING,
        author=build_author(agent_id),
        timestamp=now_ms(),
        content="",
        metadata=ToolCallPendingMeta(
            tool_name=tool_name,
            call_id=call_id,
            params={"path": "/tmp/x"},
            tier=tier,  # type: ignore[arg-type]
            initiating_agent=agent_id,
        ).model_dump(),
    )
    store.append(evt)
    return evt


def _post_room_api(client: TestClient) -> str:
    r = client.post("/rooms", json={"type": "free_chat"})
    assert r.status_code == 201
    return str(r.json()["id"])


# ---------------------------------------------------------------------------
# §1 Happy path — approve
# ---------------------------------------------------------------------------


class TestConfirmApproveHappyPath:
    def test_approve_appends_tool_call_from_record(self, tmp_path: Any) -> None:
        """approve → TOOL_CALL with tool_name/call_id/params from the pending record."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id, call_id="call_happy")

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()

        assert r.status_code == 200
        data = r.json()
        appended = data["appended_event"]
        # Backend-authoritative: tool_name/call_id/author from record, not request
        assert appended["type"] == "tool_call"
        assert appended["metadata"]["tool_name"] == "apply_edit"
        assert appended["metadata"]["call_id"] == "call_happy"
        assert appended["metadata"]["params"] == {"path": "/tmp/x"}
        assert appended["author"] == "agent:operator"  # from initiating_agent in record

    def test_approve_author_from_pending_record(self, tmp_path: Any) -> None:
        """author of approved TOOL_CALL = agent:<initiating_agent from record>."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id, agent_id="coordinator")

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()

        assert r.status_code == 200
        assert r.json()["appended_event"]["author"] == "agent:coordinator"

    def test_approve_turn_events_in_response(self, tmp_path: Any) -> None:
        """ConfirmResponse.turn_events contains appended TOOL_CALL."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id)

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()

        assert r.status_code == 200
        turn_events = r.json()["turn_events"]
        assert any(e["type"] == "tool_call" for e in turn_events)


# ---------------------------------------------------------------------------
# §2 Idempotency — double-approve
# ---------------------------------------------------------------------------


class TestConfirmIdempotency:
    def test_double_approve_second_returns_already_resolved(self, tmp_path: Any) -> None:
        """Second approve of same pending_event_id → already_resolved (layer 1)."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id, call_id="call_idem")

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r1 = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
            r2 = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()

        assert r1.status_code == 200
        assert r2.status_code == 422
        assert r2.json()["stage"] == "append"
        assert r2.json()["reason"] == "already_resolved"

    def test_double_approve_produces_single_tool_call_and_result(self, tmp_path: Any) -> None:
        """Double-approve → exactly one TOOL_CALL in room history (no double-execute)."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id, call_id="call_once")

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
            client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
            all_events = ctx.writer_store.get_room_events(room_id)

        ctx.shutdown()

        tool_calls = [e for e in all_events if e.type == EventType.TOOL_CALL]
        assert len(tool_calls) == 1  # exactly one, no double-execution


# ---------------------------------------------------------------------------
# §3 Cancel path
# ---------------------------------------------------------------------------


class TestConfirmCancel:
    def test_cancel_appends_tool_call_cancelled(self, tmp_path: Any) -> None:
        """cancel → TOOL_CALL_CANCELLED appended, no TOOL_CALL."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id, call_id="call_cancel")

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "cancel"},
            )
            all_events = ctx.writer_store.get_room_events(room_id)

        ctx.shutdown()

        assert r.status_code == 200
        appended = r.json()["appended_event"]
        assert appended["type"] == "tool_call_cancelled"
        assert appended["metadata"]["call_id"] == "call_cancel"

        assert not any(e.type == EventType.TOOL_CALL for e in all_events)
        assert not any(e.type == EventType.TOOL_RESULT for e in all_events)

    def test_approve_after_cancel_is_already_resolved(self, tmp_path: Any) -> None:
        """After cancel, approve of same pending_event_id → already_resolved."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id, call_id="call_cancelled")

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "cancel"},
            )
            r2 = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()

        assert r2.status_code == 422
        assert r2.json()["reason"] == "already_resolved"


# ---------------------------------------------------------------------------
# §4 Room-state gate (Y3)
# ---------------------------------------------------------------------------


class TestConfirmRoomStateGate:
    def test_confirm_on_closed_room_fails_with_room_closed(self, tmp_path: Any) -> None:
        """closed room → stage:append reason:room_closed (explicit handler check)."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store, state="closed")
        pending = _append_pending(ctx.writer_store, room_id)

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()

        assert r.status_code == 422
        body = r.json()
        assert body["stage"] == "append"
        assert body["reason"] == "room_closed"
        assert body["appended_event_id"] is None

    def test_confirm_on_non_closed_room_proceeds(self, tmp_path: Any) -> None:
        """Non-closed rooms (setup, exploration, etc.) are allowed."""
        for state in ("setup", "exploration", "convergence", "snapshot_pending"):
            ctx = _make_ctx(tmp_path / f"db_{state}.db")
            room_id = _make_room(ctx.writer_store, state=state)
            pending = _append_pending(ctx.writer_store, room_id, call_id=f"call_{state}")

            with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
                r = client.post(
                    f"/rooms/{room_id}/confirm",
                    json={"pending_event_id": pending.id, "decision": "approve"},
                )
            ctx.shutdown()

            assert r.status_code == 200, f"state={state} should be allowed"


# ---------------------------------------------------------------------------
# §5 No-forge / backend-authoritative
# ---------------------------------------------------------------------------


class TestConfirmNoForge:
    def test_extra_fields_in_request_rejected(self, tmp_path: Any) -> None:
        """ConfirmRequest extra='forbid': unknown fields → 422 Unprocessable Entity."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id)

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={
                    "pending_event_id": pending.id,
                    "decision": "approve",
                    "tool_name": "evil_tool",  # forge attempt
                    "params": {"inject": True},
                },
            )
        ctx.shutdown()

        assert r.status_code == 422  # extra="forbid" rejects at schema layer

    def test_unknown_pending_event_id_fails_closed(self, tmp_path: Any) -> None:
        """Unknown pending_event_id → stage:append (nothing persisted, safe to retry)."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": generate_event_id(), "decision": "approve"},
            )
        ctx.shutdown()

        assert r.status_code == 422
        assert r.json()["stage"] == "append"
        assert r.json()["reason"] == "not_found"

    def test_non_tool_call_pending_event_id_fails_closed(self, tmp_path: Any) -> None:
        """pending_event_id pointing at a non-TOOL_CALL_PENDING event → fail closed."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        # Append a plain UTTERANCE event
        utterance = Event(
            id=generate_event_id(),
            room_id=room_id,
            type=EventType.UTTERANCE,
            author="agent:operator",
            timestamp=now_ms(),
            content="hello",
        )
        ctx.writer_store.append(utterance)

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": utterance.id, "decision": "approve"},
            )
        ctx.shutdown()

        assert r.status_code == 422
        assert r.json()["stage"] == "append"
        assert r.json()["reason"] == "not_found"

    def test_room_not_found(self, tmp_path: Any) -> None:
        """Unknown room_id → 422 (not_found)."""
        ctx = _make_ctx(tmp_path / "db.db")

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                "/rooms/room_doesnotexist/confirm",
                json={"pending_event_id": generate_event_id(), "decision": "approve"},
            )
        ctx.shutdown()

        assert r.status_code == 422
        assert r.json()["reason"] == "not_found"


# ---------------------------------------------------------------------------
# §6 Cross-turn call_id collision (Y2)
# ---------------------------------------------------------------------------


class TestConfirmCrossTurnY2:
    def test_prior_turn_result_does_not_false_reject_fresh_pending(self, tmp_path: Any) -> None:
        """Position-anchored: TOOL_RESULT(abc) before TOOL_CALL_PENDING(abc) does not resolve it.

        A prior-turn TOOL_RESULT for call_id='abc' must not cause the still-pending
        check to treat a LATER TOOL_CALL_PENDING(abc) as already resolved.
        This matches the B2 snapshot predicate exactly (Y2 cross-turn collision).
        """
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)

        # Append a prior-turn TOOL_RESULT with call_id="abc" (turn 1)
        prior_result = Event(
            id=generate_event_id(),
            room_id=room_id,
            type=EventType.TOOL_RESULT,
            author="agent:operator",
            timestamp=now_ms(),
            content="prior result",
            metadata=ToolResultMeta(call_id="abc", success=True).model_dump(),
        )
        ctx.writer_store.append(prior_result)

        # Append a fresh TOOL_CALL_PENDING with same call_id="abc" (turn 5)
        pending = _append_pending(ctx.writer_store, room_id, call_id="abc")

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            # Should succeed: prior-turn result is BEFORE the pending event (position-anchored)
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()

        assert r.status_code == 200
        assert r.json()["appended_event"]["type"] == "tool_call"
        assert r.json()["appended_event"]["metadata"]["call_id"] == "abc"


# ---------------------------------------------------------------------------
# §7 Writer-executor atomicity (N3)
# ---------------------------------------------------------------------------


class TestConfirmWriterExecutorAtomicity:
    def test_confirm_runs_on_writer_executor(self, tmp_path: Any) -> None:
        """The confirm closure runs on ctx.writer_executor (single-writer atomic)."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id, call_id="call_atomic")

        writer_thread_id: list[int] = []
        original_submit = ctx.writer_executor.submit

        import threading

        def _tracking_submit(fn: Any, *args: Any, **kwargs: Any) -> Any:
            def _wrapped() -> Any:
                writer_thread_id.append(threading.get_ident())
                return fn(*args, **kwargs)

            return original_submit(_wrapped)

        ctx.writer_executor.submit = _tracking_submit  # type: ignore[assignment]

        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()

        assert r.status_code == 200
        # The confirm closure ran on the writer executor thread
        assert writer_thread_id, "confirm did not run on writer_executor"
        assert len(set(writer_thread_id)) == 1  # single thread (max_workers=1)


# ---------------------------------------------------------------------------
# §8 Pending-resolution consistency (R0-A Y1)
# ---------------------------------------------------------------------------


class TestPendingResolutionConsistency:
    """snapshot.tool_calls_pending_confirm ⟺ endpoint still-pending use the same predicate."""

    def test_unresolved_listed_by_snapshot_and_confirmable(self, tmp_path: Any) -> None:
        """Unresolved pending: snapshot lists it AND endpoint allows confirm (same predicate)."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id, call_id="call_cons_pend")

        # Snapshot sees it as pending
        room = ctx.writer_store.get_room(room_id)
        assert room is not None
        events = ctx.writer_store.get_room_events(room_id)
        snap = produce_snapshot(events, room, snapshot_at=now_ms())
        assert any(r.event_id == pending.id for r in snap.tool_calls_pending_confirm)

        # Endpoint also sees it as still-pending (confirm succeeds)
        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()
        assert r.status_code == 200

    def test_resolved_not_listed_by_snapshot_and_already_resolved(self, tmp_path: Any) -> None:
        """Resolved pending: snapshot drops it AND endpoint returns already_resolved."""
        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id, call_id="call_cons_res")

        # First confirm resolves it
        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r1 = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        assert r1.status_code == 200

        # Snapshot now drops it from the pending list
        room = ctx.writer_store.get_room(room_id)
        assert room is not None
        events = ctx.writer_store.get_room_events(room_id)
        snap = produce_snapshot(events, room, snapshot_at=now_ms())
        assert not any(r.event_id == pending.id for r in snap.tool_calls_pending_confirm)

        # Endpoint also returns already_resolved
        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r2 = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()
        assert r2.status_code == 422
        assert r2.json()["reason"] == "already_resolved"


# ---------------------------------------------------------------------------
# §9 Execute-stage failure (R0-A Y2, ADR-030 D5 do-not-reverse)
# ---------------------------------------------------------------------------


class TestConfirmExecuteStage:
    """Executor failure after TOOL_CALL appended: do-not-reverse + idempotent re-confirm."""

    def test_executor_failure_execute_stage_error_durable_idempotent(self, tmp_path: Any) -> None:
        """executor raises → 500 stage:execute; TOOL_CALL durable; re-confirm already_resolved.

        ADR-030 D5: approval already landed — do NOT re-confirm, reconcile via replay.
        Layer-1 still-pending check catches the orphaned TOOL_CALL on re-confirm.
        """
        from unittest.mock import patch

        ctx = _make_ctx(tmp_path / "db.db")
        room_id = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, room_id, call_id="call_exec_fail")

        # First confirm: executor raises AFTER TOOL_CALL has been appended
        with (
            patch(
                "orchestrator.api.app.execute_pending_tool_calls",
                side_effect=RuntimeError("executor boom"),
            ),
            TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client,
        ):
            r1 = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )

        assert r1.status_code == 500
        body = r1.json()
        assert body["stage"] == "execute"
        assert body["appended_event_id"] is not None
        assert "executor boom" in body["reason"]

        # TOOL_CALL is durable (do-not-reverse invariant, ADR-030 D5)
        all_events = ctx.writer_store.get_room_events(room_id)
        tool_calls = [e for e in all_events if e.type == EventType.TOOL_CALL]
        assert len(tool_calls) == 1
        assert tool_calls[0].id == body["appended_event_id"]

        # Re-confirm → already_resolved (layer-1 catches the orphaned TOOL_CALL)
        with TestClient(_make_test_app(ctx), headers=_auth_headers(ctx)) as client:
            r2 = client.post(
                f"/rooms/{room_id}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()
        assert r2.status_code == 422
        assert r2.json()["stage"] == "append"
        assert r2.json()["reason"] == "already_resolved"
