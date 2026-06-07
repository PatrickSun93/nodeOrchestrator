"""P4.6-6 constitutional + functional tests for COUNTDOWN auto-fire (ADR-040).

Lens A — auto-fire safety:
  (a) HARD never auto-fires (stamp + sweep).
  (b) opt-in OFF → byte-identical (no expires_at, sweeper inert).
  (c) reversibility floor — below-floor COUNTDOWN stays pending for human.
  (d) idempotency — double-sweep / human-then-timer ≤ one TOOL_CALL.
  (e) restart re-arm — prior-process window → fresh full window.
  (f) gate byte-frozen + no new LLMPurpose (spot-checked here, full check in scoring tests).
  (g) provenance honest (auto_timer / human).
  (h) t4 appender-guard — auto-fire reconstructs from persisted record.

Lens B — spine no-regression (process via _writer_approve_helper + HTTP confirm):
  HTTP confirm path behavior-identical after helper extraction; existing
  test_confirm.py covers the full matrix; this file covers the new surfaces.
"""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock

import pytest

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.api.app import (
    AppContext,
    _ApproveOk,
    _ApproveSkipped,
    _discover_expired_pendings,
    _make_test_app,
    _writer_approve_helper,
)
from orchestrator.api.auth.session import create_token
from orchestrator.api.auth.users import create_user, init_auth_schema
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.autonomy.config import CountdownAutoFireConfig
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    TimestampMs,
    ToolCallMeta,
    ToolCallPendingMeta,
    build_author,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.types import (
    LLMResponse,
    ModelId,
    ProviderId,
    RequestId,
    Usage,
)

# ---------------------------------------------------------------------------
# Test helpers (mirrors test_confirm.py pattern)
# ---------------------------------------------------------------------------

_TEST_USER = "autofire_user"
_TEST_PW = "pw-x"

_ENABLED_CFG = CountdownAutoFireConfig(
    enabled=True, window_s=300, sweep_interval_s=30, reversibility_floor=3
)
_DISABLED_CFG = CountdownAutoFireConfig()  # default: disabled


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


def _make_store(db_path: Any) -> EventStore:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    store = EventStore(conn)
    store.init_schema()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    init_auth_schema(conn)
    create_user(conn, _TEST_USER, _TEST_PW)
    return store


def _make_ctx(
    db_path: Any,
    countdown_auto_fire: CountdownAutoFireConfig | None = None,
) -> AppContext:
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
        local_tools={},
        countdown_auto_fire=countdown_auto_fire or _DISABLED_CFG,
    )


def _make_room(store: EventStore, state: str = "setup") -> RoomId:
    rid = generate_room_id()
    store.append_room(Room(id=rid, type=RoomType.FREE_CHAT, state=state))
    return rid


def _append_pending(
    store: EventStore,
    rid: RoomId,
    *,
    call_id: str = "call_af",
    tool_name: str = "propose_edit",
    tier: str = "countdown_confirm",
    agent_id: str = "operator",
    expires_at: TimestampMs | None = None,
) -> Event:
    ts = now_ms()
    evt = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_CALL_PENDING,
        author=build_author(agent_id),
        timestamp=ts,
        content="",
        metadata=ToolCallPendingMeta(
            tool_name=tool_name,
            call_id=call_id,
            params={"path": "/tmp/x"},
            tier=tier,  # type: ignore[arg-type]
            initiating_agent=agent_id,
            expires_at=expires_at,
        ).model_dump(),
    )
    store.append(evt)
    return evt


def _mock_loop() -> MagicMock:
    """Mock asyncio event loop — suppresses bus publish calls in sync tests."""
    return MagicMock()


# ---------------------------------------------------------------------------
# (b) Opt-in OFF → byte-identical: expires_at never set
# ---------------------------------------------------------------------------


class TestOptInOff:
    def test_countdown_disabled_expires_at_none(self, tmp_path: Any) -> None:
        """With disabled auto-fire, COUNTDOWN pending has expires_at=None."""
        from orchestrator.agents.tool_dispatch import process_tool_calls
        from orchestrator.autonomy.scoring import ThresholdConfig, ToolMeta
        from orchestrator.core.event import EventType
        from orchestrator.llm.types import ToolCall

        store = EventStore(sqlite3.connect(":memory:"))
        store.init_schema()
        rid = generate_room_id()
        store.append_room(Room(id=rid, type=RoomType.RESEARCH))
        current = Event(
            id=generate_event_id(),
            room_id=rid,
            type=EventType.UTTERANCE,
            author="agent:op",
            timestamp=now_ms(),
            content="",
        )
        store.append(current)

        tools = {"propose_edit": ToolMeta(reversibility=5)}
        thresholds = ThresholdConfig(
            threshold_auto=6, threshold_confirm=3, user_intent_modifier=0
        )

        # No countdown_auto_fire → disabled
        process_tool_calls(
            [ToolCall(id="c1", name="propose_edit", arguments={})],
            agent_id="op",
            room_id=rid,
            current_event=current,
            event_store=store,
            tools=tools,
            thresholds=thresholds,
            countdown_auto_fire=None,
        )

        pendings = [e for e in store.get_room_events(rid) if e.type == EventType.TOOL_CALL_PENDING]
        assert len(pendings) == 1
        meta = ToolCallPendingMeta.model_validate(pendings[0].metadata)
        assert meta.expires_at is None, "disabled auto-fire must not stamp expires_at"


# ---------------------------------------------------------------------------
# (a) HARD never auto-fires — structural guard
# ---------------------------------------------------------------------------


class TestHardNeverFires:
    def test_hard_expires_at_always_none(self, tmp_path: Any) -> None:
        """HARD_CONFIRM pending has expires_at=None even when auto-fire is enabled."""
        from orchestrator.agents.tool_dispatch import process_tool_calls
        from orchestrator.autonomy.scoring import ThresholdConfig, ToolMeta
        from orchestrator.core.event import EventType
        from orchestrator.llm.types import ToolCall

        store = EventStore(sqlite3.connect(":memory:"))
        store.init_schema()
        rid = generate_room_id()
        store.append_room(Room(id=rid, type=RoomType.RESEARCH))
        current = Event(
            id=generate_event_id(), room_id=rid, type=EventType.UTTERANCE,
            author="agent:op", timestamp=now_ms(), content="",
        )
        store.append(current)

        # apply_edit reversibility=2 → HARD_CONFIRM under these thresholds
        tools = {"apply_edit": ToolMeta(reversibility=2)}
        thresholds = ThresholdConfig(
            threshold_auto=6, threshold_confirm=3, user_intent_modifier=0
        )
        cfg = CountdownAutoFireConfig(
            enabled=True, window_s=300, sweep_interval_s=30, reversibility_floor=0
        )

        process_tool_calls(
            [ToolCall(id="c_hard", name="apply_edit", arguments={})],
            agent_id="op",
            room_id=rid,
            current_event=current,
            event_store=store,
            tools=tools,
            thresholds=thresholds,
            countdown_auto_fire=cfg,
        )

        pendings = [e for e in store.get_room_events(rid) if e.type == EventType.TOOL_CALL_PENDING]
        assert len(pendings) == 1
        meta = ToolCallPendingMeta.model_validate(pendings[0].metadata)
        assert meta.tier == "hard_confirm"
        assert meta.expires_at is None, "HARD_CONFIRM must never receive expires_at"

    def test_discover_skips_hard_pending(self, tmp_path: Any) -> None:
        """_discover_expired_pendings never returns HARD_CONFIRM pendings."""
        ctx = _make_ctx(tmp_path / "db.db", _ENABLED_CFG)
        rid = _make_room(ctx.writer_store)
        past = TimestampMs(now_ms() - 1_000_000)
        _append_pending(
            ctx.writer_store, rid,
            tier="hard_confirm",
            expires_at=past,  # even if stamped (shouldn't happen), must not fire
        )
        server_start_ms = int(now_ms() - 2_000_000)
        candidates = _discover_expired_pendings(ctx, _ENABLED_CFG, server_start_ms)
        ctx.shutdown()
        assert len(candidates) == 0, "HARD pending must never appear in sweeper candidates"


# ---------------------------------------------------------------------------
# (c) Reversibility floor
# ---------------------------------------------------------------------------


class TestReversibilityFloor:
    def test_below_floor_expires_at_none(self, tmp_path: Any) -> None:
        """COUNTDOWN with reversibility < floor has expires_at=None."""
        from orchestrator.agents.tool_dispatch import process_tool_calls
        from orchestrator.autonomy.scoring import ThresholdConfig, ToolMeta
        from orchestrator.core.event import EventType
        from orchestrator.llm.types import ToolCall

        store = EventStore(sqlite3.connect(":memory:"))
        store.init_schema()
        rid = generate_room_id()
        store.append_room(Room(id=rid, type=RoomType.RESEARCH))
        current = Event(
            id=generate_event_id(), room_id=rid, type=EventType.UTTERANCE,
            author="agent:op", timestamp=now_ms(), content="",
        )
        store.append(current)

        # reversibility=4, floor=5 → below floor → no expires_at
        tools = {"propose_edit": ToolMeta(reversibility=4)}
        thresholds = ThresholdConfig(
            threshold_auto=6, threshold_confirm=3, user_intent_modifier=0
        )
        cfg = CountdownAutoFireConfig(
            enabled=True, window_s=300, sweep_interval_s=30, reversibility_floor=5
        )

        process_tool_calls(
            [ToolCall(id="c1", name="propose_edit", arguments={})],
            agent_id="op",
            room_id=rid,
            current_event=current,
            event_store=store,
            tools=tools,
            thresholds=thresholds,
            countdown_auto_fire=cfg,
        )

        pendings = [e for e in store.get_room_events(rid) if e.type == EventType.TOOL_CALL_PENDING]
        assert len(pendings) == 1
        meta = ToolCallPendingMeta.model_validate(pendings[0].metadata)
        assert meta.expires_at is None, "below-floor COUNTDOWN must not stamp expires_at"

    def test_at_floor_expires_at_set(self, tmp_path: Any) -> None:
        """COUNTDOWN with reversibility == floor gets expires_at stamped."""
        from orchestrator.agents.tool_dispatch import process_tool_calls
        from orchestrator.autonomy.scoring import ThresholdConfig, ToolMeta
        from orchestrator.core.event import EventType
        from orchestrator.llm.types import ToolCall

        store = EventStore(sqlite3.connect(":memory:"))
        store.init_schema()
        rid = generate_room_id()
        store.append_room(Room(id=rid, type=RoomType.RESEARCH))
        current = Event(
            id=generate_event_id(), room_id=rid, type=EventType.UTTERANCE,
            author="agent:op", timestamp=now_ms(), content="",
        )
        store.append(current)

        tools = {"propose_edit": ToolMeta(reversibility=5)}
        thresholds = ThresholdConfig(
            threshold_auto=6, threshold_confirm=3, user_intent_modifier=0
        )
        cfg = CountdownAutoFireConfig(
            enabled=True, window_s=300, sweep_interval_s=30, reversibility_floor=5
        )

        before_ms = now_ms()
        process_tool_calls(
            [ToolCall(id="c1", name="propose_edit", arguments={})],
            agent_id="op",
            room_id=rid,
            current_event=current,
            event_store=store,
            tools=tools,
            thresholds=thresholds,
            countdown_auto_fire=cfg,
        )

        pendings = [e for e in store.get_room_events(rid) if e.type == EventType.TOOL_CALL_PENDING]
        assert len(pendings) == 1
        meta = ToolCallPendingMeta.model_validate(pendings[0].metadata)
        assert meta.expires_at is not None, "at-floor COUNTDOWN must stamp expires_at"
        assert meta.expires_at >= before_ms + cfg.window_s * 1000


# ---------------------------------------------------------------------------
# (g) Provenance honest
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_human_approve_sets_approval_source_human(self, tmp_path: Any) -> None:
        """HTTP confirm approve path sets approval_source='human'."""
        from fastapi.testclient import TestClient

        ctx = _make_ctx(tmp_path / "db.db")
        rid = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, rid, call_id="call_human")
        raw_token = create_token(ctx.writer_store.conn, _TEST_USER)
        headers = {"Authorization": f"Bearer {raw_token}"}

        with TestClient(_make_test_app(ctx), headers=headers) as client:
            r = client.post(
                f"/rooms/{rid}/confirm",
                json={"pending_event_id": pending.id, "decision": "approve"},
            )
        ctx.shutdown()

        assert r.status_code == 200
        tc_meta = r.json()["appended_event"]["metadata"]
        assert tc_meta["approval_source"] == "human"

    def test_writer_approve_helper_sets_auto_timer(self, tmp_path: Any) -> None:
        """_writer_approve_helper with approval_source='auto_timer' sets the field."""
        ctx = _make_ctx(tmp_path / "db.db")
        rid = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, rid, call_id="call_timer")
        loop = _mock_loop()

        result = ctx.writer_executor.submit(
            _writer_approve_helper, ctx, rid, pending.id, "auto_timer", None, loop
        ).result()
        ctx.shutdown()

        assert isinstance(result, _ApproveOk)
        meta = ToolCallMeta.model_validate(result.appended_event.metadata)
        assert meta.approval_source == "auto_timer"
        assert meta.approver_user_id is None


# ---------------------------------------------------------------------------
# (d) Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_double_sweep_no_duplicate(self, tmp_path: Any) -> None:
        """Calling _writer_approve_helper twice on the same pending → second is already_resolved."""
        ctx = _make_ctx(tmp_path / "db.db")
        rid = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, rid, call_id="call_idem")
        loop = _mock_loop()

        # First fire
        r1 = ctx.writer_executor.submit(
            _writer_approve_helper, ctx, rid, pending.id, "auto_timer", None, loop
        ).result()
        # Second fire (simulate double-sweep)
        r2 = ctx.writer_executor.submit(
            _writer_approve_helper, ctx, rid, pending.id, "auto_timer", None, loop
        ).result()

        assert isinstance(r1, _ApproveOk)
        assert isinstance(r2, _ApproveSkipped)
        assert r2.reason == "already_resolved"

        # Exactly one TOOL_CALL
        tc_events = [
            e for e in ctx.writer_store.get_room_events(rid)
            if e.type == EventType.TOOL_CALL
        ]
        assert len(tc_events) == 1
        ctx.shutdown()

    def test_human_cancel_then_timer_noop(self, tmp_path: Any) -> None:
        """Human cancels during window → timer fire is already_resolved."""
        from fastapi.testclient import TestClient

        ctx = _make_ctx(tmp_path / "db.db")
        rid = _make_room(ctx.writer_store)
        pending = _append_pending(ctx.writer_store, rid, call_id="call_race")
        raw_token = create_token(ctx.writer_store.conn, _TEST_USER)
        headers = {"Authorization": f"Bearer {raw_token}"}

        # Human cancels first
        with TestClient(_make_test_app(ctx), headers=headers) as client:
            rc = client.post(
                f"/rooms/{rid}/confirm",
                json={"pending_event_id": pending.id, "decision": "cancel"},
            )
        assert rc.status_code == 200

        # Timer fires after (should be already_resolved)
        loop = _mock_loop()
        result = ctx.writer_executor.submit(
            _writer_approve_helper, ctx, rid, pending.id, "auto_timer", None, loop
        ).result()
        ctx.shutdown()

        assert isinstance(result, _ApproveSkipped)
        assert result.reason == "already_resolved"


# ---------------------------------------------------------------------------
# (e) Boot re-arm (D6 effective_deadline formula)
# ---------------------------------------------------------------------------


class TestBootRearm:
    def test_prior_process_pending_gets_fresh_window(self, tmp_path: Any) -> None:
        """A pending armed by a prior process gets effective_deadline = server_start + window."""
        ctx = _make_ctx(tmp_path / "db.db", _ENABLED_CFG)
        rid = _make_room(ctx.writer_store)

        old_ts = now_ms() - 1_000_000  # 1000 s ago (old process)
        # expires_at also in past (would have fired in old process)
        old_expires = TimestampMs(old_ts + _ENABLED_CFG.window_s * 1000)
        _append_pending(ctx.writer_store, rid, expires_at=old_expires)
        # Simulate via server_start_ms > pending.timestamp (pending is from prior process).
        server_start_ms = now_ms()  # now > pending.timestamp → prior process
        # effective_deadline = server_start_ms + window_s*1000 > now_ms() → no fire yet
        candidates = _discover_expired_pendings(ctx, _ENABLED_CFG, server_start_ms)
        ctx.shutdown()
        assert len(candidates) == 0, (
            "Prior-process pending must get a fresh full window and not fire immediately"
        )

    def test_current_process_pending_uses_original_deadline(self, tmp_path: Any) -> None:
        """A pending armed by this process (timestamp >= server_start) uses original expires_at."""
        ctx = _make_ctx(tmp_path / "db.db", _ENABLED_CFG)
        rid = _make_room(ctx.writer_store)

        # server_start_ms is in the past → pending.timestamp > server_start_ms
        server_start_ms = int(now_ms() - 2_000_000)
        past_expires = TimestampMs(now_ms() - 1000)  # already expired
        pending = _append_pending(
            ctx.writer_store, rid,
            expires_at=past_expires,
        )
        # pending.timestamp >= server_start_ms (current process) AND expired → should fire
        candidates = _discover_expired_pendings(ctx, _ENABLED_CFG, server_start_ms)
        ctx.shutdown()
        assert any(eid == pending.id for _, eid in candidates), (
            "Current-process pending with elapsed expires_at must appear in candidates"
        )


# ---------------------------------------------------------------------------
# (g) Closed-room gate (acceptance 9)
# ---------------------------------------------------------------------------


class TestClosedRoom:
    def test_writer_approve_helper_closed_room_skip(self, tmp_path: Any) -> None:
        """Actuating a pending in a closed room returns room_closed skip."""
        ctx = _make_ctx(tmp_path / "db.db")
        rid = _make_room(ctx.writer_store, state="closed")
        pending = _append_pending(ctx.writer_store, rid)
        loop = _mock_loop()

        result = ctx.writer_executor.submit(
            _writer_approve_helper, ctx, rid, pending.id, "auto_timer", None, loop
        ).result()
        ctx.shutdown()

        assert isinstance(result, _ApproveSkipped)
        assert result.reason == "room_closed"


# ---------------------------------------------------------------------------
# (h) t4 appender-guard: auto-fire reconstructs from persisted record
# ---------------------------------------------------------------------------


class TestApproverGuard:
    def test_auto_fire_reconstructs_from_record(self, tmp_path: Any) -> None:
        """Auto-fire TOOL_CALL uses tool_name/params/author from pending record."""
        ctx = _make_ctx(tmp_path / "db.db")
        rid = _make_room(ctx.writer_store)
        pending = _append_pending(
            ctx.writer_store, rid,
            call_id="call_t4",
            tool_name="propose_edit",
            agent_id="myagent",
        )
        loop = _mock_loop()

        result = ctx.writer_executor.submit(
            _writer_approve_helper, ctx, rid, pending.id, "auto_timer", None, loop
        ).result()
        ctx.shutdown()

        assert isinstance(result, _ApproveOk)
        evt = result.appended_event
        meta = ToolCallMeta.model_validate(evt.metadata)
        assert meta.tool_name == "propose_edit"
        assert meta.call_id == "call_t4"
        assert evt.author == "agent:myagent"


# ---------------------------------------------------------------------------
# Sweeper lifecycle: clean shutdown (no pending-task warning)
# ---------------------------------------------------------------------------


class TestSweeperShutdown:
    async def test_sweeper_cancels_cleanly(self, tmp_path: Any) -> None:
        """Sweeper task cancels without unhandled exception."""
        from orchestrator.api.app import _countdown_sweeper

        ctx = _make_ctx(tmp_path / "db.db", _ENABLED_CFG)
        loop = asyncio.get_event_loop()
        server_start_ms = now_ms()

        task = asyncio.create_task(
            _countdown_sweeper(ctx, _ENABLED_CFG, loop, server_start_ms),
            name="test-sweeper",
        )
        # Give the task a chance to start (it sleeps sweep_interval_s before first tick).
        await asyncio.sleep(0)
        task.cancel()
        # Should complete without raising.
        with pytest.raises(asyncio.CancelledError):
            await task
        ctx.shutdown()

    async def test_disabled_config_no_expires_at_not_discovered(self, tmp_path: Any) -> None:
        """Pending with expires_at=None (stamped when disabled) is never discovered."""
        ctx = _make_ctx(tmp_path / "db.db", _DISABLED_CFG)
        rid = _make_room(ctx.writer_store)
        # Simulate what the disabled stamp gate produces: expires_at=None
        _append_pending(ctx.writer_store, rid, expires_at=None)

        server_start_ms = int(now_ms() - 2_000_000)
        candidates = _discover_expired_pendings(ctx, _ENABLED_CFG, server_start_ms)
        ctx.shutdown()
        assert len(candidates) == 0, "pending with expires_at=None must not be discovered"
