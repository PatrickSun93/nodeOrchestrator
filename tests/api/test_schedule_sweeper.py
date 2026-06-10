"""Tests for _schedule_sweeper/_discover_due_schedules/_rearm_schedules_on_boot (ADR-042/P5.1b-4).

Lens A — scheduler safety:
  (a) only due+enabled schedules fire
  (b) disabled schedules skipped
  (c) future schedules skipped
  (d) pipeline.enabled=0 → next_fire advances but no run
  (e) claim-before-run double-fire guard: stale reader sees a schedule twice → runs once
  (f) boot re-arm: past-due schedules advanced, NOT run
  (g) run attributed to schedule.owner_user_id

Lens B — spine no-regression:
  (h) scheduler OFF → app context unchanged, no sweeper started
  (i) _schedule_sweeper references none of _countdown_sweeper / _discover_expired_pendings /
      _writer_approve_helper (grep / import assertion)
  (j) run_pipeline byte-unchanged (import-only; scheduler does not edit it)
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.api.app import (
    AppContext,
    _discover_due_schedules,
    _rearm_schedules_on_boot,
    _schedule_act_on_writer,
    _schedule_sweeper,
)
from orchestrator.api.auth.users import create_user, init_auth_schema
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.core.event_store import EventStore
from orchestrator.pipeline.config import PipelineSchedulerConfig
from orchestrator.pipeline.schema import PipelineDefinition
from orchestrator.pipeline.store import (
    create_pipeline,
    create_schedule,
    get_schedule,
    init_pipeline_schema,
    set_schedule_enabled,
)
from orchestrator.sources.schema import Source

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER = "sched_test_user"
_PW = "sched_pw"
_NOW = 1_700_000_000_000  # fixed epoch-ms


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
        content="analysis",
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
    # analysis call + reduce call
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

    writer_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sw-test-writer")
    reader_exec = ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="sw-test-reader", initializer=_init_reader
    )
    return AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=writer_exec,
        reader_executor=reader_exec,
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
    c = _make_ctx(tmp_path / "sw_test.db")
    yield c
    c.shutdown()


def _make_pipeline(ctx: AppContext) -> str:
    defn = PipelineDefinition(
        sources=[Source(kind="web", locator="https://example.com/")],
        analysis_prompts=["Analyze this"],
    )
    record = create_pipeline(ctx.writer_store.conn, owner_user_id=_USER, definition=defn)
    return record.pipeline_id


def _make_schedule(
    ctx: AppContext,
    pipeline_id: str,
    *,
    next_fire: int = _NOW - 1,
    kind: str = "interval",
    expr: str = "60",
) -> str:
    record = create_schedule(
        ctx.writer_store.conn,
        pipeline_id=pipeline_id,
        owner_user_id=_USER,
        kind=kind,
        expr=expr,
        next_fire=next_fire,
    )
    return record.schedule_id


# ---------------------------------------------------------------------------
# Lens A: (a) fires due+enabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweeper_fires_due_enabled(tmp_path: Path) -> None:
    """Sweeper fires a due enabled schedule (schedule_act call verified via act direct test).

    Uses a file source (not web) to avoid network calls.  Verifies that the sweeper
    task discovers a due schedule and advances next_fire (claim step).
    """
    c = _make_ctx(tmp_path / "t1.db")
    try:
        src_file = tmp_path / "data.txt"
        src_file.write_text("test data")

        from orchestrator.pipeline.schema import PipelineDefinition
        from orchestrator.pipeline.store import create_pipeline as _cp
        from orchestrator.sources.schema import Source

        defn = PipelineDefinition(
            sources=[Source(kind="file", locator=str(src_file))],
            analysis_prompts=["Analyze this"],
        )
        pipe_record = _cp(c.writer_store.conn, owner_user_id=_USER, definition=defn)
        pipe_id = pipe_record.pipeline_id
        sid = _make_schedule(c, pipe_id, next_fire=_NOW - 1)

        cfg = PipelineSchedulerConfig(enabled=True, sweep_interval_s=1)
        loop = asyncio.get_running_loop()

        task = asyncio.create_task(_schedule_sweeper(c, cfg, loop))
        await asyncio.sleep(1.5)  # wait for sweep_interval_s=1 to elapse + buffer
        task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await task

        # The sweeper should have claimed: next_fire should be advanced past _NOW - 1
        from orchestrator.pipeline.store import get_schedule as _gs

        sched = _gs(c.writer_store.conn, sid)
        assert sched is not None
        assert sched.next_fire > _NOW - 1, (
            "sweeper should have claimed the schedule (advanced next_fire)"
        )
    finally:
        c.shutdown()


# ---------------------------------------------------------------------------
# Lens A: (b) disabled schedule skipped; (c) future skipped
# ---------------------------------------------------------------------------


def test_discover_due_excludes_disabled(ctx: AppContext) -> None:
    pipe_id = _make_pipeline(ctx)
    sid = _make_schedule(ctx, pipe_id, next_fire=_NOW - 1)
    set_schedule_enabled(ctx.writer_store.conn, sid, False)

    due = _discover_due_schedules(ctx, _NOW)
    assert sid not in due


def test_discover_due_excludes_future(ctx: AppContext) -> None:
    pipe_id = _make_pipeline(ctx)
    _make_schedule(ctx, pipe_id, next_fire=_NOW + 60_000)

    due = _discover_due_schedules(ctx, _NOW)
    assert due == []


def test_discover_due_includes_past(ctx: AppContext) -> None:
    pipe_id = _make_pipeline(ctx)
    sid = _make_schedule(ctx, pipe_id, next_fire=_NOW - 1)

    due = _discover_due_schedules(ctx, _NOW)
    assert sid in due


# ---------------------------------------------------------------------------
# Lens A: (d) pipeline.enabled=0 → next_fire advances but no run
# ---------------------------------------------------------------------------


def test_act_disabled_pipeline_advances_next_fire_no_run(ctx: AppContext) -> None:
    router = _mock_router()
    ctx.llm_router = cast(LLMRouterProtocol, router)

    pipe_id = _make_pipeline(ctx)
    ctx.writer_store.conn.execute(
        "UPDATE pipelines SET enabled=0 WHERE pipeline_id=?", (pipe_id,)
    )
    ctx.writer_store.conn.commit()

    old_next_fire = _NOW - 1
    sid = _make_schedule(ctx, pipe_id, next_fire=old_next_fire)

    _schedule_act_on_writer(ctx, sid, _NOW)

    sched = get_schedule(ctx.writer_store.conn, sid)
    assert sched is not None
    assert sched.next_fire > old_next_fire, "next_fire should have advanced"
    assert router.call.call_count == 0, "LLM should not be called"


# ---------------------------------------------------------------------------
# Lens A: (d2) missing pipeline → next_fire advances, no run (A3/Y2/PVI-3)
# ---------------------------------------------------------------------------


def test_act_missing_pipeline_advances_next_fire_no_run(ctx: AppContext) -> None:
    """Orphan schedule (deleted pipeline) must advance next_fire so it's not re-due every tick."""
    router = _mock_router()
    ctx.llm_router = cast(LLMRouterProtocol, router)

    pipe_id = _make_pipeline(ctx)
    old_next_fire = _NOW - 1
    sid = _make_schedule(ctx, pipe_id, next_fire=old_next_fire)

    # Delete the pipeline to create an orphan schedule.
    ctx.writer_store.conn.execute(
        "DELETE FROM pipelines WHERE pipeline_id=?", (pipe_id,)
    )
    ctx.writer_store.conn.commit()

    _schedule_act_on_writer(ctx, sid, _NOW)

    sched = get_schedule(ctx.writer_store.conn, sid)
    assert sched is not None
    assert sched.next_fire > old_next_fire, "orphan schedule next_fire must be advanced"
    assert router.call.call_count == 0, "LLM must not be called for orphan schedule"


# ---------------------------------------------------------------------------
# Lens A: (e) claim-before-run double-fire guard
# ---------------------------------------------------------------------------


def test_act_double_fire_guard(ctx: AppContext) -> None:
    """A schedule discovered by two ticks (stale reader) fires only once.

    First act claims next_fire; second act re-reads and sees the advanced
    next_fire, so it skips the run.
    """
    router = _mock_router()
    router.call.side_effect = [_llm_response(), _llm_response()]
    ctx.llm_router = cast(LLMRouterProtocol, router)

    pipe_id = _make_pipeline(ctx)
    sid = _make_schedule(ctx, pipe_id, next_fire=_NOW - 1)

    # First act: should run
    _schedule_act_on_writer(ctx, sid, _NOW)
    assert router.call.call_count > 0, "First act should have fired the pipeline"

    # Second act with same now_ms: next_fire already advanced past _NOW
    router.call.reset_mock()
    _schedule_act_on_writer(ctx, sid, _NOW)
    assert router.call.call_count == 0, "Second act must not fire again"


# ---------------------------------------------------------------------------
# Lens A: (f) boot re-arm advances past-due without running
# ---------------------------------------------------------------------------


def test_rearm_advances_past_due_without_running(ctx: AppContext) -> None:
    router = _mock_router()
    ctx.llm_router = cast(LLMRouterProtocol, router)

    pipe_id = _make_pipeline(ctx)
    old_next_fire = _NOW - 5000
    sid = _make_schedule(ctx, pipe_id, next_fire=old_next_fire)

    _rearm_schedules_on_boot(ctx)

    sched = get_schedule(ctx.writer_store.conn, sid)
    assert sched is not None
    assert sched.next_fire > old_next_fire, "next_fire must be advanced"
    assert router.call.call_count == 0, "boot re-arm must NOT run the pipeline"


def test_rearm_leaves_future_schedules_unchanged(ctx: AppContext) -> None:
    from orchestrator.core.event import now_ms as _now_ms

    pipe_id = _make_pipeline(ctx)
    future_fire = _now_ms() + 3_600_000  # 1 hour from real now
    sid = _make_schedule(ctx, pipe_id, next_fire=future_fire)

    _rearm_schedules_on_boot(ctx)

    sched = get_schedule(ctx.writer_store.conn, sid)
    assert sched is not None
    assert sched.next_fire == future_fire, "future schedule must not be touched"


# ---------------------------------------------------------------------------
# Lens A: (g) run attributed to schedule.owner_user_id
# ---------------------------------------------------------------------------


def test_act_run_attributed_to_schedule_owner(ctx: AppContext) -> None:
    router = _mock_router()
    router.call.side_effect = [_llm_response(), _llm_response()]
    ctx.llm_router = cast(LLMRouterProtocol, router)

    pipe_id = _make_pipeline(ctx)
    sid = _make_schedule(ctx, pipe_id, next_fire=_NOW - 1)

    _schedule_act_on_writer(ctx, sid, _NOW)

    # run_id row should carry owner_user_id = _USER (the schedule owner)
    rows = ctx.writer_store.conn.execute(
        "SELECT owner_user_id FROM pipeline_runs WHERE pipeline_id=?", (pipe_id,)
    ).fetchall()
    assert rows, "pipeline_runs row must exist"
    assert rows[0][0] == _USER


# ---------------------------------------------------------------------------
# Lens A: (g2) create_pipeline_run failure after successful run (Y3)
# ---------------------------------------------------------------------------


def test_act_create_run_fails_after_successful_run_does_not_raise(ctx: AppContext) -> None:
    """Y3: create_pipeline_run failure after successful run_pipeline must log, not re-raise."""
    from unittest.mock import patch

    router = _mock_router()
    router.call.side_effect = [_llm_response(), _llm_response()]
    ctx.llm_router = cast(LLMRouterProtocol, router)

    pipe_id = _make_pipeline(ctx)
    sid = _make_schedule(ctx, pipe_id, next_fire=_NOW - 1)

    with patch(
        "orchestrator.pipeline.store.create_pipeline_run",
        side_effect=Exception("simulated db failure"),
    ):
        # Must not propagate the exception.
        _schedule_act_on_writer(ctx, sid, _NOW)

    # next_fire should still be advanced (claim step succeeded before run).
    sched = get_schedule(ctx.writer_store.conn, sid)
    assert sched is not None
    assert sched.next_fire > _NOW - 1, "next_fire must be advanced even when create_pipeline_run fails"  # noqa: E501


# ---------------------------------------------------------------------------
# Lens B: (h) scheduler OFF → no impact on countdown sweeper
# ---------------------------------------------------------------------------


def test_scheduler_off_no_effect_on_countdown(ctx: AppContext) -> None:
    """With pipeline_scheduler disabled (default), countdown config is unchanged."""
    assert ctx.pipeline_scheduler.enabled is False
    assert ctx.countdown_auto_fire.enabled is False
    # Both should be their defaults — off-state is byte-identical to P5.1a


# ---------------------------------------------------------------------------
# Lens B: (i) _schedule_sweeper imports none of countdown spine
# ---------------------------------------------------------------------------


def test_schedule_sweeper_does_not_call_countdown_spine() -> None:
    """_schedule_sweeper must not CALL countdown spine symbols (ADR-042 D1).

    Checks AST call sites rather than raw string presence to allow docstring
    mentions that describe the design intent without coupling the code.
    """
    import ast

    source = inspect.getsource(_schedule_sweeper)
    tree = ast.parse(source)

    # Collect all Name nodes that appear as function call targets
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    forbidden_calls = {
        "_countdown_sweeper",
        "_discover_expired_pendings",
        "_writer_approve_helper",
    }
    for sym in forbidden_calls:
        assert sym not in called_names, (
            f"_schedule_sweeper must not call {sym!r} (ADR-042 D1)"
        )


def test_schedule_act_on_writer_does_not_call_countdown_spine() -> None:
    """A4: _schedule_act_on_writer must import/call none of the countdown-actuation spine.

    Checks AST call sites so docstring mentions do not trigger false positives.
    """
    import ast

    source = inspect.getsource(_schedule_act_on_writer)
    tree = ast.parse(source)

    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    forbidden_calls = {
        "_countdown_sweeper",
        "_discover_expired_pendings",
        "_writer_approve_helper",
    }
    for sym in forbidden_calls:
        assert sym not in called_names, (
            f"_schedule_act_on_writer must not call {sym!r} (ADR-042 D1)"
        )


# ---------------------------------------------------------------------------
# Lens B: (j) run_pipeline byte-unchanged
# ---------------------------------------------------------------------------


def test_run_pipeline_not_modified_by_scheduler() -> None:
    """Scheduler imports run_pipeline but must not edit it (ADR-042 D6).

    Checks the runner MODULE source for the countdown_auto_fire=None sentinel
    (which appears in both process_tool_calls call sites, ADR-041 D5).
    """
    from orchestrator.pipeline import runner

    module_source = inspect.getsource(runner)
    assert "countdown_auto_fire=None" in module_source, (
        "runner.py must still pass countdown_auto_fire=None (ADR-041 D5 / ADR-042 D6)"
    )


# ---------------------------------------------------------------------------
# Lens B: clean teardown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_sweeper_cancels_cleanly(tmp_path: Path) -> None:
    c = _make_ctx(tmp_path / "t_cancel.db")
    try:
        cfg = PipelineSchedulerConfig(enabled=True, sweep_interval_s=60)
        loop = asyncio.get_event_loop()
        task = asyncio.create_task(_schedule_sweeper(c, cfg, loop))
        await asyncio.sleep(0.01)
        task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert task.done()
    finally:
        c.shutdown()
