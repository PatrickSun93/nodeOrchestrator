"""P8-1 regression tests: room state seeded as 'setup' + derive from event stream.

These tests exercise the REAL CROSS-TURN HTTP PATH (POST /intent), NOT an
in-memory Room(state=...) rebuild — that in-memory trick is what masked the
original bug (see tests/rooms/test_runtime.py:169-262 for the masked pattern).

Acceptance criteria:
- POST /rooms seeds default_initial_state ("setup"), not the model default ("open").
- After state_transition events are present, GET /snapshot derives current state
  from the event stream (not the stale rooms.state column).
- A DECISION event sent via POST /intent in "diagnosed" state triggers
  diagnosed → fix_proposed in the HTTP write path (derive_room_state active).
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from orchestrator.api.app import AppContext, _make_test_app
from orchestrator.api.auth.session import create_token
from orchestrator.api.auth.users import create_user, init_auth_schema
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    StateTransitionMeta,
    generate_event_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.memory.store import init_memory_schema
from orchestrator.reentry.store import init_reentry_schema
from orchestrator.rooms.state_machine import derive_room_state

# ---------------------------------------------------------------------------
# Minimal fixtures for cross-turn HTTP path tests
# ---------------------------------------------------------------------------

_USER = "state-test-user"
_PW = "state-test-pw"


def _make_ctx_for_state_tests() -> AppContext:
    """Build a minimal AppContext for state-derive tests (no real agents needed)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from orchestrator.agents.dispatch import LLMRouterProtocol
    from orchestrator.llm.types import (
        LLMResponse,
        ModelId,
        ProviderId,
        RequestId,
        Usage,
    )
    from orchestrator.pipeline.store import init_pipeline_schema

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    writer_store = EventStore(conn)
    writer_store.init_schema()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    init_auth_schema(conn)
    init_pipeline_schema(conn)
    init_memory_schema(conn)
    init_reentry_schema(conn)
    create_user(conn, _USER, _PW)

    reader_store = EventStore(conn)

    _reader_local: threading.local = threading.local()
    _reader_conns: list[sqlite3.Connection] = []

    mock_router = MagicMock(spec=LLMRouterProtocol)
    mock_router.call.return_value = LLMResponse(
        request_id=RequestId(generate_event_id()),
        content="ok",
        tool_calls=[],
        model_id_requested=ModelId("mock"),
        model_id_used=ModelId("mock"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=1, output_tokens=1),
        latency_ms=0,
        finish_reason="stop",
    )

    return AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=ThreadPoolExecutor(max_workers=1),
        reader_executor=ThreadPoolExecutor(max_workers=1),
        bus=RoomEventBus(),
        available_agents={},
        available_skills={},
        regex_registry={},
        tools={},
        llm_router=mock_router,
        reader_local=_reader_local,
        reader_conns=_reader_conns,
    )


def _auth_client(ctx: AppContext) -> TestClient:
    raw_token = create_token(ctx.writer_store.conn, _USER)
    return TestClient(
        _make_test_app(ctx),
        raise_server_exceptions=True,
        headers={"Authorization": f"Bearer {raw_token}"},
    )


def _append_state_transition(
    ctx: AppContext, room_id: RoomId, prior_state: str, new_state: str
) -> Event:
    """Append a STATE_TRANSITION event directly to the writer store; return the event."""
    event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.STATE_TRANSITION,
        author="system",
        timestamp=now_ms(),
        content="",
        metadata=StateTransitionMeta(prior_state=prior_state, new_state=new_state).model_dump(),
    )
    ctx.writer_store.append(event)
    return event


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateRoomSeedsSetup:
    def test_create_room_state_is_setup(self) -> None:
        """POST /rooms returns state='setup', not the model default 'open' (P8-1)."""
        ctx = _make_ctx_for_state_tests()
        with _auth_client(ctx) as client:
            r = client.post("/rooms", json={"type": "research"})
        assert r.status_code == 201
        assert r.json()["state"] == "setup", (
            f"Expected state='setup' but got {r.json()['state']!r} — "
            "create-seed fix (P8-1) not applied"
        )

    def test_all_room_types_seed_setup(self) -> None:
        """All 5 RoomTypes seed default_initial_state='setup'."""
        ctx = _make_ctx_for_state_tests()
        for rtype in ["research", "bug_fix", "code_review", "idea_validation", "free_chat"]:
            with _auth_client(ctx) as client:
                r = client.post("/rooms", json={"type": rtype})
            assert r.status_code == 201
            assert r.json()["state"] == "setup", (
                f"{rtype}: expected state='setup', got {r.json()['state']!r}"
            )


class TestDeriveRoomStateFromEvents:
    def test_snapshot_derives_state_after_transition(self) -> None:
        """GET /snapshot reflects derived state from event stream, not stale rooms.state column.

        This is the cross-turn HTTP path test (P8-1 acceptance criterion):
        state_transition events appended to the store, snapshot derives 'exploration'
        even though the rooms.state column was never updated.
        """
        ctx = _make_ctx_for_state_tests()
        with _auth_client(ctx) as client:
            create_r = client.post("/rooms", json={"type": "research"})
            room_id_str = create_r.json()["id"]
            rid = RoomId(room_id_str)

            # Append state_transition: setup → exploration (server-side, as run_turn would do).
            _append_state_transition(ctx, rid, prior_state="setup", new_state="exploration")

            # Snapshot must derive 'exploration' from the event stream.
            snap_r = client.get(f"/rooms/{room_id_str}/snapshot")
        assert snap_r.status_code == 200
        assert snap_r.json()["room_state"] == "exploration", (
            f"snapshot room_state={snap_r.json()['room_state']!r}; "
            "expected 'exploration' derived from event stream"
        )

    def test_cross_turn_http_path_decision_triggers_state_transition(self) -> None:
        """REAL CROSS-TURN HTTP PATH: POST /intent with type=decision in 'diagnosed'
        state triggers diagnosed→fix_proposed via derive_room_state in _write_and_turn.

        Without the P8-1 fix, _write_and_turn would read the stale rooms.state column
        ('setup') and next_room_state would see state='setup' — the DECISION event
        would not match any setup→... rule and no transition would fire.
        """
        ctx = _make_ctx_for_state_tests()
        with _auth_client(ctx) as client:
            create_r = client.post("/rooms", json={"type": "bug_fix"})
            room_id_str = create_r.json()["id"]
            rid = RoomId(room_id_str)

            # Simulate prior turns having advanced the state to 'diagnosed'.
            # These are server-side events (as run_turn would append them).
            _append_state_transition(ctx, rid, prior_state="setup", new_state="reproduced")
            diagnosed_ev = _append_state_transition(
                ctx, rid, prior_state="reproduced", new_state="diagnosed"
            )

            # The rooms.state column still reads "setup" (never updated — deliberate).
            db_room = ctx.writer_store.get_room(rid)
            assert db_room is not None
            assert db_room.state == "setup", (
                "test pre-condition: column not updated (expected stale 'setup')"
            )

            # Cross-turn HTTP path: send DECISION event — should trigger diagnosed→fix_proposed.
            # based_on requires ≥1 EventId; use the diagnosed transition event as the anchor.
            intent_r = client.post(
                f"/rooms/{room_id_str}/intent",
                json={
                    "type": "decision",
                    "content": "the fix is confirmed",
                    "metadata": {"based_on": [diagnosed_ev.id]},
                },
            )
            assert intent_r.status_code == 200, f"intent failed: {intent_r.text}"

        # Verify state_transition fix_proposed event was appended by run_turn.
        all_events = ctx.writer_store.get_room_events(rid)
        transition_events = [e for e in all_events if e.type == EventType.STATE_TRANSITION]
        fix_proposed_transitions = [
            e
            for e in transition_events
            if StateTransitionMeta.model_validate(e.metadata).new_state == "fix_proposed"
        ]
        assert fix_proposed_transitions, (
            "Expected diagnosed→fix_proposed transition event appended by _write_and_turn, "
            "but none found. derive_room_state was not used on the HTTP path."
        )

        # Verify derived state via the event stream.
        derived = derive_room_state(all_events, seed="setup")
        assert derived == "fix_proposed", f"derive_room_state returned {derived!r}"
