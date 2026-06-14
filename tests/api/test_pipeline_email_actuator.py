"""Tests for the pipeline-email actuator: _actuate_pipeline_emails + dry-run path (ADR-043 D2-D6).

P5.1c-3/4 tests:
  - live-mode actuation happy-path (send_email pending + matching recipient)
  - dry-run: no actuation, OBSERVATION with PipelineEmailDryRunMeta recorded
  - OFF (email_enabled=False): no actuation, no observation
  - recipient mismatch in live mode: pending stays waiting
  - idempotency: re-calling actuator on already-resolved pending is a no-op
  - 3-state transition: dry-run first, then live
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.api.app import (
    AppContext,
    _actuate_pipeline_emails,
)
from orchestrator.api.auth.users import create_user, init_auth_schema
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.core.event import (
    Event,
    EventType,
    PipelineEmailDryRunMeta,
    RoomId,
    ToolCallPendingMeta,
    build_author,
    generate_event_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.pipeline.schema import PipelineDefinition, PipelineScheduleRecord
from orchestrator.pipeline.store import (
    create_pipeline,
    create_schedule,
    init_pipeline_schema,
    promote_schedule_email_live,
    set_schedule_email_optin,
)
from orchestrator.sources.schema import Source

_USER = "email_act_user"
_PW = "pw"
_NOW = 1_700_000_000_000
_RECIPIENT = "alice@example.com"


def _llm_response() -> Any:
    from orchestrator.llm.types import (
        LLMResponse,
        ModelId,
        ProviderId,
        Usage,
        generate_request_id,
    )

    return LLMResponse(
        request_id=generate_request_id(),
        content="analysis result",
        tool_calls=[],
        model_id_requested=ModelId("m"),
        model_id_used=ModelId("m"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=1, output_tokens=1),
        latency_ms=0,
        finish_reason="stop",
    )


def _mock_router() -> MagicMock:
    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = [_llm_response(), _llm_response()]
    return router


def _make_ctx(db_path: Path, router: MagicMock | None = None) -> AppContext:
    writer_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    writer_store = EventStore(writer_conn)
    writer_store.init_schema()
    writer_conn.execute("PRAGMA journal_mode=WAL")
    writer_conn.commit()
    init_auth_schema(writer_conn)
    init_pipeline_schema(writer_conn)
    create_user(writer_conn, _USER, _PW)

    reader_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    reader_store = EventStore(reader_conn)
    _reader_local: threading.local = threading.local()
    _reader_conns: list[sqlite3.Connection] = []
    lock = threading.Lock()

    def _init_reader() -> None:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _reader_local.conn = conn
        _reader_local.store = EventStore(conn)
        with lock:
            _reader_conns.append(conn)

    return AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="em-test-wr"),
        reader_executor=ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="em-test-rd", initializer=_init_reader
        ),
        bus=RoomEventBus(),
        available_agents={},
        available_skills={},
        regex_registry={},
        tools={},
        llm_router=router or _mock_router(),
        reader_local=_reader_local,
        reader_conns=_reader_conns,
    )


@pytest.fixture
def ctx(tmp_path: Path) -> Generator[AppContext, None, None]:
    c = _make_ctx(tmp_path / "email_act.db")
    yield c
    c.shutdown()


def _make_pipeline(ctx: AppContext) -> str:
    defn = PipelineDefinition(
        sources=[Source(kind="web", locator="https://example.com/")],
        analysis_prompts=["Analyze"],
    )
    return create_pipeline(ctx.writer_store.conn, owner_user_id=_USER, definition=defn).pipeline_id


def _make_schedule_record(
    ctx: AppContext,
    pipeline_id: str,
    *,
    email_enabled: bool = False,
    email_mode: str = "dry_run",
    email_recipient: str | None = None,
) -> PipelineScheduleRecord:
    rec = create_schedule(
        ctx.writer_store.conn,
        pipeline_id=pipeline_id,
        owner_user_id=_USER,
        kind="interval",
        expr="60",
        next_fire=_NOW - 1,
    )
    from orchestrator.pipeline.store import get_schedule

    if email_enabled:
        if email_recipient:
            set_schedule_email_optin(
                ctx.writer_store.conn, rec.schedule_id, recipient=email_recipient
            )
        if email_mode == "live":
            promote_schedule_email_live(ctx.writer_store.conn, rec.schedule_id)
    result = get_schedule(ctx.writer_store.conn, rec.schedule_id)
    assert result is not None
    return result


def _append_send_email_pending(
    ctx: AppContext,
    room_id: RoomId,
    *,
    to: str = _RECIPIENT,
    subject: str = "Test Subject",
    call_id: str = "call_send_email_1",
) -> Event:
    """Append a send_email TOOL_CALL_PENDING (HARD_CONFIRM) to the room."""
    evt = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_CALL_PENDING,
        author=build_author("operator"),
        timestamp=now_ms(),
        content="",
        metadata=ToolCallPendingMeta(
            tool_name="send_email",
            call_id=call_id,
            params={"to": to, "subject": subject, "body": "Hello from pipeline."},
            tier="hard_confirm",
            initiating_agent="operator",
            expires_at=None,
        ).model_dump(),
    )
    ctx.writer_store.append(evt)
    return evt


def _make_room(ctx: AppContext) -> RoomId:
    from orchestrator.core.event import generate_room_id
    from orchestrator.core.room import Room, RoomType

    rid = generate_room_id()
    ctx.writer_store.append_room(Room(id=rid, type=RoomType.FREE_CHAT, state="setup"))
    return rid


# ---------------------------------------------------------------------------
# email_enabled=False: actuator is a no-op
# ---------------------------------------------------------------------------


def test_actuate_noop_when_email_disabled(ctx: AppContext) -> None:
    """With email_enabled=False, _actuate_pipeline_emails does nothing."""
    pipe_id = _make_pipeline(ctx)
    schedule = _make_schedule_record(ctx, pipe_id, email_enabled=False)
    room_id = _make_room(ctx)
    _append_send_email_pending(ctx, room_id)

    loop = asyncio.new_event_loop()
    try:
        _actuate_pipeline_emails(ctx, schedule, room_id, loop=loop)
    finally:
        loop.close()

    # Pending remains unresolved
    events = ctx.writer_store.get_room_events(room_id)
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_calls) == 0, "no TOOL_CALL should be appended when email_enabled=False"
    observations = [e for e in events if e.type == EventType.OBSERVATION]
    assert len(observations) == 0


# ---------------------------------------------------------------------------
# dry-run mode: OBSERVATION recorded, no actuation
# ---------------------------------------------------------------------------


def test_dry_run_records_observation_no_actuation(ctx: AppContext) -> None:
    """dry-run: OBSERVATION with PipelineEmailDryRunMeta appended; pending stays waiting."""
    pipe_id = _make_pipeline(ctx)
    schedule = _make_schedule_record(
        ctx, pipe_id, email_enabled=True, email_mode="dry_run", email_recipient=_RECIPIENT
    )
    room_id = _make_room(ctx)
    _append_send_email_pending(ctx, room_id, to=_RECIPIENT)

    loop = asyncio.new_event_loop()
    try:
        _actuate_pipeline_emails(ctx, schedule, room_id, loop=loop)
    finally:
        loop.close()

    events = ctx.writer_store.get_room_events(room_id)
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_calls) == 0, "dry-run must NOT append TOOL_CALL"

    observations = [e for e in events if e.type == EventType.OBSERVATION]
    assert len(observations) == 1, "exactly one OBSERVATION for one pending"

    # Validate PipelineEmailDryRunMeta structure (structurally typed, ADR-043 D6)
    dry_meta = PipelineEmailDryRunMeta.model_validate(observations[0].metadata)
    assert dry_meta.recipient == _RECIPIENT
    assert dry_meta.subject == "Test Subject"
    assert dry_meta.would_actuate is True
    assert dry_meta.owner_user_id == _USER
    assert dry_meta.approval_source == "auto_pipeline"

    # Pending is still unresolved
    pendings = [e for e in events if e.type == EventType.TOOL_CALL_PENDING]
    assert len(pendings) == 1


def test_dry_run_would_actuate_false_on_mismatch(ctx: AppContext) -> None:
    """dry-run with recipient mismatch: OBSERVATION.would_actuate = False."""
    pipe_id = _make_pipeline(ctx)
    schedule = _make_schedule_record(
        ctx, pipe_id, email_enabled=True, email_mode="dry_run", email_recipient="other@example.com"
    )
    room_id = _make_room(ctx)
    _append_send_email_pending(ctx, room_id, to=_RECIPIENT)

    loop = asyncio.new_event_loop()
    try:
        _actuate_pipeline_emails(ctx, schedule, room_id, loop=loop)
    finally:
        loop.close()

    events = ctx.writer_store.get_room_events(room_id)
    observations = [e for e in events if e.type == EventType.OBSERVATION]
    assert len(observations) == 1
    dry_meta = PipelineEmailDryRunMeta.model_validate(observations[0].metadata)
    assert dry_meta.would_actuate is False
    assert dry_meta.recipient == _RECIPIENT


# ---------------------------------------------------------------------------
# live mode: actuation happy-path
# ---------------------------------------------------------------------------


def test_live_mode_actuates_matching_pending(ctx: AppContext) -> None:
    """live mode: send_email pending with matching recipient gets actuated."""
    pipe_id = _make_pipeline(ctx)
    schedule = _make_schedule_record(
        ctx, pipe_id, email_enabled=True, email_mode="live", email_recipient=_RECIPIENT
    )
    room_id = _make_room(ctx)
    _append_send_email_pending(ctx, room_id, to=_RECIPIENT)

    loop = asyncio.new_event_loop()
    try:
        with patch("orchestrator.tools.network_tools._make_send_email") as mock_send:
            mock_send.return_value = {"ok": True}
            # Patch _execute_local_call to avoid real tool execution in unit test
            with patch("orchestrator.tools.executor._execute_local_call") as mock_exec:
                mock_exec.return_value = {"sent": True}
                _actuate_pipeline_emails(ctx, schedule, room_id, loop=loop)
    finally:
        loop.close()

    events = ctx.writer_store.get_room_events(room_id)
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_calls) >= 1, "TOOL_CALL should be appended in live mode"

    # Verify approval_source and owner attribution
    from orchestrator.core.event import ToolCallMeta

    tc_meta = ToolCallMeta.model_validate(tool_calls[0].metadata)
    assert tc_meta.tool_name == "send_email"
    assert tc_meta.approval_source == "auto_pipeline"
    assert tc_meta.approver_user_id == _USER


# ---------------------------------------------------------------------------
# live mode: recipient mismatch → pending stays waiting
# ---------------------------------------------------------------------------


def test_live_mode_recipient_mismatch_stays_waiting(ctx: AppContext) -> None:
    """live mode: recipient mismatch → pending not actuated."""
    pipe_id = _make_pipeline(ctx)
    schedule = _make_schedule_record(
        ctx, pipe_id, email_enabled=True, email_mode="live", email_recipient="other@example.com"
    )
    room_id = _make_room(ctx)
    _append_send_email_pending(ctx, room_id, to=_RECIPIENT)

    loop = asyncio.new_event_loop()
    try:
        _actuate_pipeline_emails(ctx, schedule, room_id, loop=loop)
    finally:
        loop.close()

    events = ctx.writer_store.get_room_events(room_id)
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_calls) == 0, "mismatch → no actuation"
    observations = [e for e in events if e.type == EventType.OBSERVATION]
    assert len(observations) == 0, "no observation in live mode on mismatch"


# ---------------------------------------------------------------------------
# Case-insensitive recipient matching (R0B-Y1)
# ---------------------------------------------------------------------------


def test_live_mode_case_insensitive_recipient_match(ctx: AppContext) -> None:
    """live mode: case-insensitive recipient match actuates (Alice@Foo.com vs alice@foo.com)."""
    pipe_id = _make_pipeline(ctx)
    schedule = _make_schedule_record(
        ctx, pipe_id, email_enabled=True, email_mode="live", email_recipient="Alice@Example.Com"
    )
    room_id = _make_room(ctx)
    _append_send_email_pending(ctx, room_id, to="alice@example.com")

    loop = asyncio.new_event_loop()
    try:
        with patch("orchestrator.tools.executor._execute_local_call") as mock_exec:
            mock_exec.return_value = {"sent": True}
            _actuate_pipeline_emails(ctx, schedule, room_id, loop=loop)
    finally:
        loop.close()

    events = ctx.writer_store.get_room_events(room_id)
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_calls) >= 1, "case-insensitive match should actuate"


# ---------------------------------------------------------------------------
# Idempotency: re-invoking actuator on already-resolved pending is a no-op
# ---------------------------------------------------------------------------


def test_idempotency_no_double_send(ctx: AppContext) -> None:
    """Re-invoking _actuate_pipeline_emails on an already-resolved pending is a no-op."""
    pipe_id = _make_pipeline(ctx)
    schedule = _make_schedule_record(
        ctx, pipe_id, email_enabled=True, email_mode="live", email_recipient=_RECIPIENT
    )
    room_id = _make_room(ctx)
    _append_send_email_pending(ctx, room_id, to=_RECIPIENT)

    loop = asyncio.new_event_loop()
    try:
        with patch("orchestrator.tools.executor._execute_local_call") as mock_exec:
            mock_exec.return_value = {"sent": True}
            _actuate_pipeline_emails(ctx, schedule, room_id, loop=loop)
            # Second call: pending is already resolved
            _actuate_pipeline_emails(ctx, schedule, room_id, loop=loop)
    finally:
        loop.close()

    events = ctx.writer_store.get_room_events(room_id)
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_calls) == 1, "at-most-once: second call must not produce a second TOOL_CALL"


# ---------------------------------------------------------------------------
# 3-state transition: dry-run first, then live (P5.1c-5 test, ADR-043 D5/D6)
# ---------------------------------------------------------------------------


def test_three_state_transition_dry_run_then_live(ctx: AppContext, tmp_path: Path) -> None:
    """Freshly opted-in schedule is in dry-run (no send); only after promote → live does it send."""
    pipe_id = _make_pipeline(ctx)

    # Step 1: opt-in → dry-run
    rec = create_schedule(
        ctx.writer_store.conn,
        pipeline_id=pipe_id,
        owner_user_id=_USER,
        kind="interval",
        expr="60",
        next_fire=_NOW - 1,
    )
    sid = rec.schedule_id
    set_schedule_email_optin(ctx.writer_store.conn, sid, recipient=_RECIPIENT)

    from orchestrator.pipeline.store import get_schedule

    dry_run_sched = get_schedule(ctx.writer_store.conn, sid)
    assert dry_run_sched is not None
    assert dry_run_sched.email_enabled is True
    assert dry_run_sched.email_mode == "dry_run"

    room_id = _make_room(ctx)
    _append_send_email_pending(ctx, room_id, to=_RECIPIENT)

    loop = asyncio.new_event_loop()
    try:
        _actuate_pipeline_emails(ctx, dry_run_sched, room_id, loop=loop)
    finally:
        loop.close()

    events_after_dryrun = ctx.writer_store.get_room_events(room_id)
    assert not any(e.type == EventType.TOOL_CALL for e in events_after_dryrun), (
        "dry-run must not send"
    )
    assert any(e.type == EventType.OBSERVATION for e in events_after_dryrun), (
        "dry-run must record OBSERVATION"
    )

    # Step 2: promote → live
    promote_schedule_email_live(ctx.writer_store.conn, sid)
    live_sched = get_schedule(ctx.writer_store.conn, sid)
    assert live_sched is not None
    assert live_sched.email_mode == "live"

    room_id2 = _make_room(ctx)
    _append_send_email_pending(ctx, room_id2, to=_RECIPIENT)

    loop2 = asyncio.new_event_loop()
    try:
        with patch("orchestrator.tools.executor._execute_local_call") as mock_exec:
            mock_exec.return_value = {"sent": True}
            _actuate_pipeline_emails(ctx, live_sched, room_id2, loop=loop2)
    finally:
        loop2.close()

    events_after_live = ctx.writer_store.get_room_events(room_id2)
    assert any(e.type == EventType.TOOL_CALL for e in events_after_live), "live mode must actuate"


# ---------------------------------------------------------------------------
# PipelineEmailDryRunMeta structural typing (ADR-043 D6 R0B-Y2)
# ---------------------------------------------------------------------------


def test_pipeline_email_dry_run_meta_schema() -> None:
    """PipelineEmailDryRunMeta is a well-formed Pydantic model with required fields."""
    meta = PipelineEmailDryRunMeta(
        recipient="alice@example.com",
        subject="Hello",
        would_actuate=True,
        owner_user_id="user_x",
        approval_source="auto_pipeline",
    )
    assert meta.recipient == "alice@example.com"
    assert meta.would_actuate is True
    assert meta.approval_source == "auto_pipeline"

    # round-trip
    dumped = meta.model_dump()
    restored = PipelineEmailDryRunMeta.model_validate(dumped)
    assert restored == meta


# ---------------------------------------------------------------------------
# Y3: unknown email_mode fails closed — no actuation (ADR-043 D5)
# ---------------------------------------------------------------------------


def test_unknown_email_mode_does_not_actuate(ctx: AppContext) -> None:
    """An unknown email_mode value must not actuate (fail-closed, ADR-043 D5)."""
    pipe_id = _make_pipeline(ctx)
    # Build a schedule manually in an unknown mode by patching the record directly.
    rec = create_schedule(
        ctx.writer_store.conn,
        pipeline_id=pipe_id,
        owner_user_id=_USER,
        kind="interval",
        expr="60",
        next_fire=_NOW - 1,
    )
    # First opt-in to set email_enabled=True, then manually corrupt email_mode.
    set_schedule_email_optin(ctx.writer_store.conn, rec.schedule_id, recipient=_RECIPIENT)
    ctx.writer_store.conn.execute(
        "UPDATE pipeline_schedules SET email_mode = 'bogus_unknown' WHERE schedule_id = ?",
        (rec.schedule_id,),
    )
    ctx.writer_store.conn.commit()

    from orchestrator.pipeline.store import get_schedule

    schedule = get_schedule(ctx.writer_store.conn, rec.schedule_id)
    assert schedule is not None
    assert schedule.email_enabled is True
    assert schedule.email_mode == "bogus_unknown"

    room_id = _make_room(ctx)
    _append_send_email_pending(ctx, room_id, to=_RECIPIENT)

    loop = asyncio.new_event_loop()
    try:
        _actuate_pipeline_emails(ctx, schedule, room_id, loop=loop)
    finally:
        loop.close()

    events = ctx.writer_store.get_room_events(room_id)
    tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_calls) == 0, "unknown email_mode must not actuate (fail-closed)"
    observations = [e for e in events if e.type == EventType.OBSERVATION]
    assert len(observations) == 0, "unknown email_mode must not record observation"
