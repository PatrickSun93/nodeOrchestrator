"""FastAPI application factory and route handlers (ADR-025 D1/D2).

P3.2-1: AppContext type + endpoint declarations (stub handlers for OpenAPI).
P3.2-2: create_app factory + read handler implementations.
P3.2-3: WS live stream + RoomEventBus integration + executor wiring.
P3.2-4: POST /intent write path + forge-prevention + llm_adapter.
P4.5-3: fail-closed auth boundary (_configure shared step, login/logout,
         WS pre-accept check, app.state.ctx for middleware ctx access).
"""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
import threading
import time
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NamedTuple

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.agents.loader import load_agents
from orchestrator.agents.schema import Agent
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.api.wire import (
    ConfirmError,
    ConfirmRequest,
    ConfirmResponse,
    Event,
    IntentError,
    IntentRequest,
    IntentResponse,
    Room,
    Snapshot,
)
from orchestrator.autonomy.config import CountdownAutoFireConfig, load_countdown_auto_fire_config
from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.bootstrap import load_and_validate_llm_layer
from orchestrator.core.event import (
    PENDING_RESOLUTION_TYPES,
    EventId,
    EventNotFoundError,
    EventType,
    InvalidParentError,
    MetadataValidationError,
    RoomId,
    RoomNotFoundError,
    TimestampMs,
    ToolCallCancelledMeta,
    ToolCallMeta,
    ToolCallPendingMeta,
    build_author,
    build_user_author,
    generate_event_id,
    generate_room_id,
    now_ms,
    validate_metadata,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room as _CoreRoom
from orchestrator.core.room import RoomType
from orchestrator.derived.snapshot import produce_snapshot
from orchestrator.llm.config_loader import load_tools_config
from orchestrator.llm.types import LLMRequest, LLMResponse
from orchestrator.mcp.client import MCPSession
from orchestrator.pipeline.config import PipelineSchedulerConfig, load_pipeline_scheduler_config
from orchestrator.skills.loader import load_skills
from orchestrator.skills.schema import Skill
from orchestrator.tools.executor import LocalToolRegistry, execute_pending_tool_calls
from orchestrator.tools.local import build_local_tool_registry

if TYPE_CHECKING:
    from orchestrator.core.event import ToolCallPendingMeta
    from orchestrator.pipeline.schema import PipelineScheduleRecord
    from orchestrator.plugins.provenance import PluginRegistry, _RegistryRefuseAll
    from orchestrator.sandbox.posture import PostureResolver

PAYLOAD_LIMIT_BYTES = 65_536  # 64 KiB

# ADR-033 D1: bounded turn-loop constants.
# MAX_TURN_LOOP_PASSES = N re-dispatch passes after pass 0 (total dispatch_turn calls ≤ 1+N=5).
MAX_TURN_LOOP_PASSES: int = 4

# ADR-033 D3 condition 4 / D4: wall-clock deadline for re-dispatch overhead (passes 1…N).
# HONEST SCOPE: this constant caps the time spent on re-dispatch passes AFTER pass 0.
# Pass 0 (run_turn + execute_pending_tool_calls) is NOT bounded by this constant — its
# dominant term is agents x provider_timeout_s (up to 4 x 600s for claude_code_cli).
# A true pass-0 / turn wall-clock cap requires async cancellation (ADR-028 D5 / P4.2).
# Cross-room head-of-line: the single ThreadPoolExecutor(max_workers=1) serialises all
# rooms; pass 0 blocks them for up to agents x provider_timeout_s regardless of this cap.
# This constant limits re-dispatch overhead only — still allows the 4-hop flagship chain.
# Checked at re-dispatch pass boundaries (between passes, never mid-pass).
MAX_REDISPATCH_WALL_CLOCK_S: float = 120.0


@dataclass
class AppContext:
    """Shared application state — one instance per running server."""

    writer_store: EventStore
    reader_store: EventStore
    writer_executor: ThreadPoolExecutor
    reader_executor: ThreadPoolExecutor
    bus: RoomEventBus
    available_agents: dict[str, Agent]
    available_skills: dict[str, Skill]
    regex_registry: dict[tuple[str, int], re.Pattern[str]]
    tools: dict[str, ToolMeta]
    llm_router: LLMRouterProtocol
    # Cycle-2 executor fields (ADR-028 D1/D2): default-valued for backward compat with tests.
    mcp_sessions: dict[str, MCPSession] = field(default_factory=dict)
    local_tools: LocalToolRegistry = field(default_factory=dict)
    sandbox_root: Path = field(default_factory=lambda: Path.cwd())
    # Per-thread reader connections (ADR-025 D6 RW7): each reader_executor worker owns
    # its own SQLite connection. reader_store is the fallback for tests/single-thread use.
    reader_local: threading.local = field(default_factory=threading.local)
    reader_conns: list[sqlite3.Connection] = field(default_factory=list)
    # COUNTDOWN auto-fire config (ADR-040 D7). Default OFF (fail-closed) for test compat.
    countdown_auto_fire: CountdownAutoFireConfig = field(default_factory=CountdownAutoFireConfig)
    # Pipeline scheduler config (ADR-042 D7). Default OFF (fail-closed) for test compat.
    pipeline_scheduler: PipelineSchedulerConfig = field(default_factory=PipelineSchedulerConfig)
    # config_dir: retained so plugin management routes can resolve config/plugins.yaml.
    # D-A: _plugin_registry is a local in _build_context (not retained on AppContext);
    # config_dir is not recoverable from sandbox_root (sandbox_root = config_dir.parent).
    # Default-valued for backward compat with existing test AppContext constructions.
    config_dir: Path = field(default_factory=Path.cwd)

    def get_reader_store(self) -> EventStore:
        """Return the per-thread EventStore for the calling reader_executor worker.

        Falls back to reader_store when called from a thread that has no initialised
        thread-local store (e.g. test fixtures that omit the initializer).
        """
        store: EventStore | None = getattr(self.reader_local, "store", None)
        return store if store is not None else self.reader_store

    def get_reader_conn(self) -> sqlite3.Connection:
        """Return the per-thread SQLite connection for the calling reader_executor worker.

        Falls back to reader_store.conn when no thread-local connection is available.
        """
        conn: sqlite3.Connection | None = getattr(self.reader_local, "conn", None)
        return conn if conn is not None else self.reader_store.conn

    def shutdown(self) -> None:
        """Tear down executors and DB connections on server stop."""
        self.writer_executor.shutdown(wait=True)
        self.reader_executor.shutdown(wait=True)
        self.writer_store.conn.close()
        # Per-thread reader connections (production path: non-empty after RW7 fix)
        for conn in self.reader_conns:
            conn.close()
        # Legacy single reader connection (test path / fallback; always present)
        if not self.reader_conns:
            self.reader_store.conn.close()


class _CreateRoomBody(BaseModel):
    """Request body for POST /rooms."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: RoomType


class _LoginRequest(BaseModel):
    """Request body for POST /login (ADR-039 D3). extra=forbid is the forge guard."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    user_id: str
    password: str


class _LoginResponse(BaseModel):
    """Response body for POST /login (ADR-039 D3). Documents OpenAPI contract."""

    model_config = ConfigDict(frozen=True)
    user_id: str


class _LogoutResponse(BaseModel):
    """Response body for POST /logout (ADR-039 D3). Documents OpenAPI contract."""

    model_config = ConfigDict(frozen=True)
    status: str


class _AppendFailedError(Exception):
    """append() failed — nothing persisted, safe to retry (ADR-025 D5)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _TurnFailedError(Exception):
    """run_turn failed after a successful append — intent IS persisted (ADR-025 D5)."""

    def __init__(self, reason: str, event_id: EventId) -> None:
        self.reason = reason
        self.event_id = event_id
        super().__init__(reason)


class _ConfirmAppendError(Exception):
    """confirm append failed — nothing persisted, safe to retry (ADR-030 D5)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _ConfirmExecuteError(Exception):
    """Executor raised after TOOL_CALL appended — do NOT re-confirm (ADR-030 D5)."""

    def __init__(self, reason: str, event_id: EventId) -> None:
        self.reason = reason
        self.event_id = event_id
        super().__init__(reason)


_log = logging.getLogger("orchestrator.api.app")


# ---------------------------------------------------------------------------
# Plugin management request/response models (ADR-038 D5 / P4.7-BE-T3)
# ---------------------------------------------------------------------------


class _PluginInfo(BaseModel):
    """Single entry in GET /plugins response (ADR-038 D5)."""

    model_config = ConfigDict(frozen=True)
    plugin_id: str
    enabled: bool
    version: str | None
    provenance: str
    provenance_kind: str | None
    fetched: bool


class _AdmitRequest(BaseModel):
    """Request body for POST /plugins/{id}/admit.

    extra=forbid is the forge guard (ADR-039 D7 / mirrors _LoginRequest).
    version is optional; source_url+digest are required (pinned-bundle intent).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    source_url: str
    digest: str
    version: str | None = None


class _PluginWriteResponse(BaseModel):
    """Response for all plugin write operations (boot-only; ADR-038 D2 / DP1a)."""

    model_config = ConfigDict(frozen=True)
    effect: str = "next_restart"


# ---------------------------------------------------------------------------
# Shared writer-approve outcome types + helper (ADR-040 D3 / P4.6-4)
# Used by the HTTP confirm handler and the countdown sweeper.
# ---------------------------------------------------------------------------


class _ApproveOk(NamedTuple):
    appended_event: Event
    turn_events: list[Event]


class _ApproveSkipped(NamedTuple):
    reason: str  # "already_resolved" | "room_closed" | "not_found"


class _ApproveFailed(NamedTuple):
    reason: str
    event_id: EventId


# ---------------------------------------------------------------------------
# Pipeline request/response models (ADR-041 D7 / T5)
# ---------------------------------------------------------------------------


class _PipelineCreateRequest(BaseModel):
    """Request body for POST /pipelines.

    extra=forbid: forge guard (mirrors _LoginRequest).
    owner_user_id is NOT accepted from the body — it is derived server-side
    from request.state.principal (ADR-039 D1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sources: list[dict[str, object]]
    analysis_prompts: list[str]
    output_config: dict[str, object] = {}


class _PipelineResponse(BaseModel):
    """Response for a single pipeline definition."""

    model_config = ConfigDict(frozen=True)

    pipeline_id: str
    owner_user_id: str
    enabled: bool
    created_at: int
    sources: list[dict[str, object]]
    analysis_prompts: list[str]
    output_config: dict[str, object]


class _PipelineRunResponse(BaseModel):
    """Response for POST /pipelines/{id}/run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    room_id: str
    pipeline_id: str
    succeeded: bool
    sources_read: int
    branches_succeeded: int
    branches_failed: int
    summary: str
    error: str | None


# ---------------------------------------------------------------------------
# Schedule management request/response models (ADR-042 D9 / P5.1b-5)
# ---------------------------------------------------------------------------


class _ScheduleCreateRequest(BaseModel):
    """Request body for POST /pipelines/{id}/schedules.

    extra=forbid: forge guard.  owner_user_id is NOT accepted from the body —
    it is derived server-side from request.state.principal (ADR-039 D1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    expr: str


class _ScheduleResponse(BaseModel):
    """Response for a single schedule record (ADR-042 D9 / ADR-043 D5)."""

    model_config = ConfigDict(frozen=True)

    schedule_id: str
    pipeline_id: str
    owner_user_id: str
    kind: str
    expr: str
    next_fire: int
    enabled: bool
    created_at: int
    email_enabled: bool = False
    email_mode: str = "dry_run"
    email_recipient: str | None = None


class _ScheduleEnableRequest(BaseModel):
    """Request body for PATCH /pipelines/{id}/schedules/{sid}."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool


class _ScheduleEmailOptinRequest(BaseModel):
    """Request body for POST /pipelines/{id}/schedules/{sid}/email-optin (ADR-043 D5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    email_recipient: str = Field(min_length=1)


def _writer_approve_helper(
    ctx: AppContext,
    rid: RoomId,
    pending_event_id: str,
    approval_source: Literal["human", "auto_timer", "auto_pipeline"],
    approver_user_id: str | None,
    loop: asyncio.AbstractEventLoop,
) -> _ApproveOk | _ApproveSkipped | _ApproveFailed:
    """Approve a gated TOOL_CALL_PENDING on the writer executor (ADR-040 D3).

    Implements steps 2-5 of the confirm-approve path (ADR-030 D3):
    room-state gate → still-pending check → reconstruct → execute → bus-publish.
    Must run on writer_executor (max_workers=1) for atomicity.

    Returns a discriminated outcome; callers map it to their own error semantics:
    - HTTP confirm handler: _ApproveSkipped → 422, _ApproveFailed → 500
    - Sweeper: _ApproveSkipped/_ApproveFailed → log + skip (never raises)
    """
    # Step 2: Resolve room + state gate.
    room = ctx.writer_store.get_room(rid)
    if room is None:
        return _ApproveSkipped("not_found")
    if room.state == "closed":
        return _ApproveSkipped("room_closed")

    all_events = ctx.writer_store.get_room_events(rid)
    sorted_events = sorted(all_events, key=lambda e: (e.timestamp, e.id))

    # Find the TOOL_CALL_PENDING event.
    pending_event = next(
        (
            e
            for e in sorted_events
            if e.id == pending_event_id and e.type == EventType.TOOL_CALL_PENDING
        ),
        None,
    )
    if pending_event is None:
        return _ApproveSkipped("not_found")

    pending_meta = ToolCallPendingMeta.model_validate(pending_event.metadata)
    pending_idx = sorted_events.index(pending_event)

    # Step 3: Still-pending check (idempotency layer 1) — position-anchored.
    already_resolved = any(
        later.type in PENDING_RESOLUTION_TYPES
        and str(later.metadata.get("call_id", "")) == pending_meta.call_id
        for later in sorted_events[pending_idx + 1 :]
    )
    if already_resolved:
        return _ApproveSkipped("already_resolved")

    pre_cursor = len(all_events)

    # Step 5: Approve — reconstruct TOOL_CALL from persisted record.
    # tool_name/params/author come from the gate-produced record, NEVER from the caller.
    # TOOL_CALL stays agent-authored (ADR-030 D3/ADR-039 D6 unchanged).
    tool_call_event = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_CALL,
        author=build_author(pending_meta.initiating_agent),
        timestamp=now_ms(),
        content="",
        metadata=ToolCallMeta(
            tool_name=pending_meta.tool_name,
            call_id=pending_meta.call_id,
            params=pending_meta.params,
            approver_user_id=approver_user_id,
            approval_source=approval_source,
        ).model_dump(),
    )
    try:
        ctx.writer_store.append(tool_call_event)
    except (RoomNotFoundError, InvalidParentError, MetadataValidationError) as exc:
        return _ApproveSkipped(str(exc))

    # Idempotency layer 2: executor call_id guard (ADR-028 D2).
    try:
        execute_pending_tool_calls(
            window_events=[tool_call_event],
            room_id=rid,
            event_store=ctx.writer_store,
            mcp_sessions=ctx.mcp_sessions,
            local_tools=ctx.local_tools,
            llm_router=ctx.llm_router,
        )
    except Exception as exc:
        return _ApproveFailed(str(exc), tool_call_event.id)

    new_events = ctx.writer_store.get_room_events(rid)[pre_cursor:]
    loop.call_soon_threadsafe(ctx.bus.publish, rid, new_events)
    return _ApproveOk(tool_call_event, new_events)


def _discover_expired_pendings(
    ctx: AppContext,
    cfg: CountdownAutoFireConfig,
    server_start_ms: int,
) -> list[tuple[RoomId, str]]:
    """Enumerate expired-and-probably-still-pending COUNTDOWN pendings (reader path).

    Runs on the reader_executor so discovery never blocks the event loop.
    Results are approximate (stale reader); _writer_approve_helper re-checks
    authoritatively on the writer.
    """
    results: list[tuple[RoomId, str]] = []
    current_ms = now_ms()
    reader = ctx.get_reader_store()
    for rid in reader.list_room_ids():
        events = reader.get_room_events(rid)
        sorted_events = sorted(events, key=lambda e: (e.timestamp, e.id))
        for idx, evt in enumerate(sorted_events):
            if evt.type != EventType.TOOL_CALL_PENDING:
                continue
            try:
                meta = ToolCallPendingMeta.model_validate(evt.metadata)
            except Exception:
                continue
            if meta.tier != "countdown_confirm":
                continue
            if meta.expires_at is None:
                continue
            # D6 boot re-arm: branch on whether armed by THIS process or a prior one.
            if evt.timestamp >= server_start_ms:
                effective_deadline = meta.expires_at
            else:
                effective_deadline = TimestampMs(server_start_ms + cfg.window_s * 1000)
            if current_ms < effective_deadline:
                continue
            # Pre-filter: position-anchored still-pending check (approximate).
            already_resolved = any(
                later.type in PENDING_RESOLUTION_TYPES
                and str(later.metadata.get("call_id", "")) == meta.call_id
                for later in sorted_events[idx + 1 :]
            )
            if not already_resolved:
                results.append((rid, evt.id))
    return results


async def _countdown_sweeper(
    ctx: AppContext,
    cfg: CountdownAutoFireConfig,
    loop: asyncio.AbstractEventLoop,
    server_start_ms: int,
) -> None:
    """Periodic sweeper: discovers expired COUNTDOWN pendings + actuates on writer (ADR-040 D1).

    Started in lifespan only when cfg.enabled. Cancelled cleanly in teardown.
    """
    import functools

    _log.info(
        "countdown sweeper started (window_s=%d sweep_interval_s=%d reversibility_floor=%d)",
        cfg.window_s,
        cfg.sweep_interval_s,
        cfg.reversibility_floor,
    )
    while True:
        await asyncio.sleep(cfg.sweep_interval_s)
        try:
            candidates = await loop.run_in_executor(
                ctx.reader_executor,
                lambda: _discover_expired_pendings(ctx, cfg, server_start_ms),
            )
            for rid, pending_event_id in candidates:
                result = await loop.run_in_executor(
                    ctx.writer_executor,
                    functools.partial(
                        _writer_approve_helper,
                        ctx,
                        rid,
                        pending_event_id,
                        "auto_timer",
                        None,
                        loop,
                    ),
                )
                if isinstance(result, _ApproveOk):
                    _log.info(
                        "sweeper: auto-fired rid=%s pending=%s → tool_call=%s",
                        rid,
                        pending_event_id,
                        result.appended_event.id,
                    )
                elif isinstance(result, _ApproveSkipped):
                    _log.debug(
                        "sweeper: skip rid=%s pending=%s reason=%s",
                        rid,
                        pending_event_id,
                        result.reason,
                    )
                elif isinstance(result, _ApproveFailed):
                    _log.error(
                        "sweeper: execute failed rid=%s pending=%s reason=%s",
                        rid,
                        pending_event_id,
                        result.reason,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.error("sweeper: unexpected error (loop continues): %s", exc, exc_info=True)


def _discover_due_schedules(
    ctx: AppContext,
    now_ms_val: int,
) -> list[str]:
    """Return schedule_ids whose next_fire is at or before now_ms_val (reader path).

    Runs on reader_executor so discovery never blocks the event loop.
    Results are approximate (stale reader); the act re-checks authoritatively on the writer.
    """
    from orchestrator.pipeline.store import list_due_schedules as _list_due

    records = _list_due(ctx.get_reader_conn(), now_ms_val)
    return [r.schedule_id for r in records]


# The one tool the pipeline-email actuator is allowed to headlessly actuate (ADR-043 D4).
_PIPELINE_EMAIL_TOOL = "send_email"


def _actuate_pipeline_emails(
    ctx: AppContext,
    schedule: PipelineScheduleRecord,
    run_room_id: RoomId,
    *,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Discover and actuate send_email pendings in a scheduled run's room (ADR-043 D2/D3/D4).

    Runs on the writer executor after run_pipeline + create_pipeline_run succeed.
    Returns immediately if email_enabled=False (OFF never touches pendings).

    Discovery is a dedicated scan — does NOT reuse _discover_expired_pendings
    (byte-frozen, keys on expires_at); this scan keys on tool_name == _PIPELINE_EMAIL_TOOL
    and never reads/writes expires_at.

    Eligibility gate (all must hold to actuate):
      - tool_name == _PIPELINE_EMAIL_TOOL
      - schedule.email_mode == 'live'
      - pending to matches pinned recipient, case-insensitively (both sides lowercased)

    In dry-run mode: records a typed PipelineEmailDryRunMeta OBSERVATION; does NOT actuate.
    Ineligible pendings (mismatch, not-live) are left waiting — no mutation.
    """
    if not schedule.email_enabled:
        return

    from orchestrator.core.event import EventType, ToolCallPendingMeta

    all_events = ctx.writer_store.get_room_events(run_room_id)
    sorted_events = sorted(all_events, key=lambda e: (e.timestamp, e.id))

    # Build set of resolved call_ids (already have a TOOL_CALL/TOOL_RESULT/TOOL_CALL_CANCELLED).
    resolved_call_ids: set[str] = set()
    for evt in sorted_events:
        if evt.type in PENDING_RESOLUTION_TYPES:
            cid = str(evt.metadata.get("call_id", ""))
            if cid:
                resolved_call_ids.add(cid)

    for evt in sorted_events:
        if evt.type != EventType.TOOL_CALL_PENDING:
            continue
        try:
            meta = ToolCallPendingMeta.model_validate(evt.metadata)
        except Exception:
            continue
        if meta.tool_name != _PIPELINE_EMAIL_TOOL:
            continue
        if meta.call_id in resolved_call_ids:
            continue

        # Found an unresolved send_email pending.
        if schedule.email_mode == "dry_run":
            # Dry-run: record what would be sent without actuating.
            _record_email_dry_run(
                ctx,
                run_room_id,
                meta,
                schedule=schedule,
            )
            continue
        elif schedule.email_mode != "live":
            # Unknown mode — fail-closed (ADR-043 D5: live requires email_mode explicitly set).
            _log.debug(
                "pipeline-email: unknown email_mode=%r for pending %s — skipping (fail-closed)",
                schedule.email_mode,
                evt.id,
            )
            continue

        # Live mode: eligibility gate — both non-empty + case-insensitive match (ADR-043 D3/D5).
        pending_to = str(meta.params.get("to", ""))
        pinned = schedule.email_recipient or ""
        if not (pending_to and pinned and pending_to.lower() == pinned.lower()):
            _log.debug(
                "pipeline-email: recipient mismatch for pending %s in room %s "
                "(pending_to=%r, pinned=%r) — leaving pending",
                evt.id,
                run_room_id,
                pending_to,
                pinned,
            )
            continue

        # Actuate via _writer_approve_helper (reconstruct-from-record, idempotent).
        result = _writer_approve_helper(
            ctx,
            run_room_id,
            evt.id,
            "auto_pipeline",
            schedule.owner_user_id,
            loop,
        )
        if isinstance(result, _ApproveOk):
            _log.info(
                "pipeline-email: actuated send_email pending=%s in room=%s owner=%s → tool_call=%s",
                evt.id,
                run_room_id,
                schedule.owner_user_id,
                result.appended_event.id,
            )
        elif isinstance(result, _ApproveSkipped):
            _log.debug(
                "pipeline-email: skip pending=%s room=%s reason=%s",
                evt.id,
                run_room_id,
                result.reason,
            )
        elif isinstance(result, _ApproveFailed):
            _log.error(
                "pipeline-email: execute failed pending=%s room=%s reason=%s",
                evt.id,
                run_room_id,
                result.reason,
            )


def _record_email_dry_run(
    ctx: AppContext,
    room_id: RoomId,
    pending_meta: ToolCallPendingMeta,
    *,
    schedule: PipelineScheduleRecord,
) -> None:
    """Append a PipelineEmailDryRunMeta OBSERVATION for a dry-run pass (ADR-043 D6)."""
    from orchestrator.core.event import (
        Event,
        EventType,
        PipelineEmailDryRunMeta,
        generate_event_id,
        now_ms,
    )

    pinned = schedule.email_recipient or ""
    pending_to = str(pending_meta.params.get("to", ""))
    would_actuate = bool(pending_to and pinned and pending_to.lower() == pinned.lower())

    dry_run_meta = PipelineEmailDryRunMeta(
        recipient=pending_to,
        subject=str(pending_meta.params.get("subject", "")),
        would_actuate=would_actuate,
        owner_user_id=schedule.owner_user_id,
        approval_source="auto_pipeline",
    )
    obs_event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.OBSERVATION,
        author=build_author("pipeline_email_actuator"),
        timestamp=now_ms(),
        content=(
            "[dry-run] pipeline email would be sent"
            if would_actuate
            else "[dry-run] pipeline email would not be sent (recipient mismatch)"
        ),
        metadata=dry_run_meta.model_dump(),
    )
    try:
        ctx.writer_store.append(obs_event)
    except Exception as exc:
        _log.warning("pipeline-email dry-run: failed to record observation: %s", exc)


def _schedule_act_on_writer(
    ctx: AppContext,
    schedule_id: str,
    now_ms_val: int,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Authoritative act for one due schedule on the writer executor (ADR-042 D4 / ADR-043 D2).

    Order:
      1. Re-read schedule on writer conn; skip if not still due+enabled.
      2. Fetch parent pipeline (state check deferred until after claim).
      3. Claim: advance next_fire BEFORE run (skip-to-next; crash-safe).
         Always claim regardless of pipeline state — orphan/disabled schedules
         are re-due only after the next interval, not every tick.
      4. Skip run if pipeline missing (orphan) or disabled; next_fire already
         advanced in step 3 so a restored/re-enabled pipeline resumes cleanly.
      5. Run: run_pipeline (one try) → create_pipeline_run (nested try/except
         so a log-index failure does not discard the successful run result).
      6. Email actuation (ADR-043): if schedule.email_enabled, call
         _actuate_pipeline_emails which reaches _writer_approve_helper only
         via the narrow send_email path. The COUNTDOWN spine
         (_countdown_sweeper/_discover_expired_pendings) stays uncalled.
    """
    from orchestrator.pipeline.runner import PipelineDeps, run_pipeline
    from orchestrator.pipeline.schedule import compute_next_fire
    from orchestrator.pipeline.store import (
        create_pipeline_run,
        get_pipeline,
        get_schedule,
        update_schedule_next_fire,
    )

    writer_conn = ctx.writer_store.conn

    # Step 1: authoritative re-read + still-due re-check.
    schedule = get_schedule(writer_conn, schedule_id)
    if schedule is None:
        _log.debug("schedule-sweeper: schedule %s gone, skip", schedule_id)
        return
    if not schedule.enabled or schedule.next_fire > now_ms_val:
        _log.debug(
            "schedule-sweeper: schedule %s no longer due (enabled=%s next_fire=%d now=%d), skip",
            schedule_id,
            schedule.enabled,
            schedule.next_fire,
            now_ms_val,
        )
        return

    # Step 2: fetch parent pipeline (result used after claim in step 3).
    pipeline = get_pipeline(writer_conn, schedule.pipeline_id)

    # Step 3: claim — advance next_fire BEFORE run (ADR-042 D4/D5 crash-safe).
    # Advance regardless of pipeline state so orphan/disabled schedules do not
    # re-appear as due on every subsequent tick.
    new_next_fire = compute_next_fire(schedule.kind, schedule.expr, now_ms_val)
    update_schedule_next_fire(writer_conn, schedule_id, new_next_fire)
    _log.info(
        "schedule-sweeper: claimed schedule %s, next_fire advanced to %d",
        schedule_id,
        new_next_fire,
    )

    # Step 4: pipeline-state gate (next_fire already advanced).
    if pipeline is None:
        _log.warning(
            "schedule-sweeper: pipeline %s for schedule %s missing, skip",
            schedule.pipeline_id,
            schedule_id,
        )
        return

    if not pipeline.enabled:
        _log.info(
            "schedule-sweeper: pipeline %s disabled, skipping run for schedule %s",
            schedule.pipeline_id,
            schedule_id,
        )
        return

    # Step 5: run.
    deps = PipelineDeps(
        writer_store=ctx.writer_store,
        llm_router=ctx.llm_router,
        tools=ctx.tools,
        mcp_sessions=ctx.mcp_sessions,
        local_tools=ctx.local_tools,
        sandbox_root=ctx.sandbox_root,
        bus=ctx.bus,
    )
    try:
        result = run_pipeline(
            schedule.pipeline_id,
            pipeline.definition,
            deps=deps,
            owner_user_id=schedule.owner_user_id,
        )
    except Exception as exc:
        _log.error(
            "schedule-sweeper: run_pipeline failed for schedule %s: %s",
            schedule_id,
            exc,
            exc_info=True,
        )
        return

    try:
        create_pipeline_run(
            writer_conn,
            pipeline_id=schedule.pipeline_id,
            room_id=result.room_id,
            owner_user_id=schedule.owner_user_id,
            run_id=result.run_id,
            status="completed" if result.succeeded else "failed",
        )
    except Exception as exc:
        _log.warning(
            "schedule-sweeper: create_pipeline_run failed for schedule %s (run %s succeeded): %s",
            schedule_id,
            result.run_id,
            exc,
            exc_info=True,
        )
    _log.info(
        "schedule-sweeper: run %s for schedule %s pipeline %s %s",
        result.run_id,
        schedule_id,
        schedule.pipeline_id,
        "ok" if result.succeeded else "failed",
    )

    # Step 6: email actuation (ADR-043 D2) — only when email_enabled.
    # Reaches _writer_approve_helper only via the narrow _actuate_pipeline_emails path.
    if schedule.email_enabled and loop is not None:
        try:
            _actuate_pipeline_emails(ctx, schedule, RoomId(result.room_id), loop=loop)
        except Exception as exc:
            _log.error(
                "pipeline-email: actuation failed for schedule %s run %s: %s",
                schedule_id,
                result.run_id,
                exc,
                exc_info=True,
            )


async def _schedule_sweeper(
    ctx: AppContext,
    cfg: PipelineSchedulerConfig,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Periodic sweeper: discovers due schedules + fires pipeline runs (ADR-042 D1).

    Sibling to _countdown_sweeper; shares its shape but NONE of its code.
    Started in lifespan only when cfg.enabled. Cancelled cleanly in teardown.
    """
    _log.info(
        "schedule sweeper started (sweep_interval_s=%d)",
        cfg.sweep_interval_s,
    )
    while True:
        await asyncio.sleep(cfg.sweep_interval_s)
        try:
            current_ms = now_ms()
            import functools as _functools

            due_ids = await loop.run_in_executor(
                ctx.reader_executor,
                _functools.partial(_discover_due_schedules, ctx, current_ms),
            )
            for schedule_id in due_ids:
                await loop.run_in_executor(
                    ctx.writer_executor,
                    _functools.partial(
                        _schedule_act_on_writer, ctx, schedule_id, current_ms, loop=loop
                    ),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.error(
                "schedule-sweeper: unexpected error (loop continues): %s", exc, exc_info=True
            )


def _rearm_schedules_on_boot(ctx: AppContext) -> None:
    """Advance past-due enabled schedules forward without running them (ADR-042 D5).

    Runs on the writer at lifespan startup, before the sweeper task is created.
    Schedules whose next_fire is already in the future are left untouched.
    """
    from orchestrator.pipeline.schedule import compute_next_fire
    from orchestrator.pipeline.store import (
        list_due_schedules as _list_due,
    )
    from orchestrator.pipeline.store import (
        update_schedule_next_fire,
    )

    current_ms = now_ms()
    writer_conn = ctx.writer_store.conn
    past_due = _list_due(writer_conn, current_ms)
    for schedule in past_due:
        new_next_fire = compute_next_fire(schedule.kind, schedule.expr, current_ms)
        update_schedule_next_fire(writer_conn, schedule.schedule_id, new_next_fire)
        _log.info(
            "boot re-arm: schedule %s advanced from %d to %d (skip-to-next)",
            schedule.schedule_id,
            schedule.next_fire,
            new_next_fire,
        )
    if past_due:
        _log.info("boot re-arm: advanced %d past-due schedule(s)", len(past_due))


class _NoopLLMRouter:
    """Placeholder until P3.2-4 installs RealLLMRouter via _build_context."""

    def call(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError(
            "_NoopLLMRouter: LLM router not configured. "
            "Pass a real config_dir with providers/models to create_app."
        )


def _resolve_sandbox_posture(config_dir: Path) -> PostureResolver:
    """Resolve sandbox posture from config_dir/sandbox.yaml.

    ALWAYS returns a resolver — absence or parse-failure → fail_closed().
    ADR-037 D4 / A1-3: config-absence and config-parse-failure are FAIL_CLOSED, never fail-open.
    Extracted so tests can exercise this branch without re-implementing it.
    """
    import logging

    from orchestrator.sandbox.posture import (
        PostureResolver,
        SandboxConfigError,
        load_sandbox_config,
    )

    config_path = config_dir / "sandbox.yaml"
    if config_path.exists():
        try:
            cfg = load_sandbox_config(config_path)
            return PostureResolver.from_config(cfg)
        except SandboxConfigError as exc:
            logging.getLogger("orchestrator.api.app").warning(
                "sandbox config parse failed → fail-closed (no subprocess sandbox): %s", exc
            )
            return PostureResolver.fail_closed()
    else:
        return PostureResolver.fail_closed()


def _resolve_plugin_registry(
    config_dir: Path,
) -> PluginRegistry | _RegistryRefuseAll:
    """Resolve unified plugin registry from config_dir/plugins.yaml.

    Three outcomes:
      absent        → PluginRegistry() empty dict (today's defaults; op-placed by presence).
      parseable     → PluginRegistry with the declared entries.
      malformed     → REGISTRY_REFUSE_ALL sentinel + WARNING (refuse-all, ADR-038 D2).

    The sentinel is distinct from an empty dict so load_plugins can tell
    "no config file" (absent → defaults) from "config file broken" (refuse-all).
    Follows the _resolve_sandbox_posture → fail_closed() pattern (app.py:172).
    Extracted so wired-whole tests can drive the real function.
    """
    import logging

    import yaml

    from orchestrator.llm.exceptions import ConfigError
    from orchestrator.plugins.provenance import (
        REGISTRY_REFUSE_ALL,
        PluginRegistry,
        load_plugin_registry,
    )

    config_path = config_dir / "plugins.yaml"
    if config_path.exists():
        try:
            return load_plugin_registry(config_path)
        except (ConfigError, yaml.YAMLError) as exc:
            logging.getLogger("orchestrator.api.app").warning(
                "plugins.yaml parse failed → refuse-all sentinel (ADR-038 D2): %s", exc
            )
            return REGISTRY_REFUSE_ALL
    return PluginRegistry()


def _build_context(config_dir: Path, db_path: Path) -> AppContext:
    """Build the full production AppContext from config + DB path.

    Opens two SQLite connections (writer + read-only WAL reader),
    loads agents/skills/tools/LLM layer, wires executors and pub/sub bus.
    The caller owns the returned context and must call ctx.shutdown().
    """
    # Writer: check_same_thread=False because it's created here but used on the
    # writer executor thread. The single-thread executor serializes all writes.
    writer_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    writer_store = EventStore(writer_conn)
    writer_store.init_schema()
    writer_conn.execute("PRAGMA journal_mode=WAL")
    writer_conn.commit()

    # Initialize auth tables alongside event tables (ADR-039 D2, co-located)
    from orchestrator.api.auth.users import init_auth_schema as _init_auth_schema

    _init_auth_schema(writer_conn)

    # Initialize pipeline tables alongside auth tables (ADR-041 D8, co-located)
    from orchestrator.pipeline.store import init_pipeline_schema as _init_pipeline_schema

    _init_pipeline_schema(writer_conn)

    # Initialize memory tables after event+auth+pipeline tables (FK order: memory → reentry).
    # ADR-016 D5 / ADR-021 D5: schema-init obligation; both are idempotent.
    from orchestrator.memory.store import init_memory_schema as _init_memory_schema
    from orchestrator.reentry.store import init_reentry_schema as _init_reentry_schema

    _init_memory_schema(writer_conn)
    _init_reentry_schema(writer_conn)

    # Reader: per-thread connections eliminate the concurrent-read SQLite race.
    # WAL mode allows multiple simultaneous readers; each reader_executor worker
    # gets its own connection via the initializer — no shared-connection contention.
    # reader_store below is retained as a fallback (unused by routes in production).
    reader_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    reader_store = EventStore(reader_conn)

    _reader_local: threading.local = threading.local()
    _reader_conns: list[sqlite3.Connection] = []
    _reader_conns_lock = threading.Lock()

    def _init_reader_worker() -> None:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _reader_local.conn = conn
        _reader_local.store = EventStore(conn)
        with _reader_conns_lock:
            _reader_conns.append(conn)

    writer_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="api-writer")
    reader_executor = ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="api-reader",
        initializer=_init_reader_worker,
    )
    bus = RoomEventBus()

    llm_layer = load_and_validate_llm_layer(config_dir)
    agents, regex_registry = load_agents(config_dir / "agents", models=llm_layer.models)
    skills = load_skills(config_dir / "skills")
    tools = load_tools_config(config_dir / "tools.yaml")

    # COUNTDOWN auto-fire config (ADR-040 D7 / P4.6-1). Absent → disabled (fail-closed).
    countdown_auto_fire_cfg = load_countdown_auto_fire_config(config_dir / "autonomy.yaml")

    # Pipeline scheduler config (ADR-042 D7 / P5.1b-3). Absent → disabled (fail-closed).
    pipeline_scheduler_cfg = load_pipeline_scheduler_config(config_dir / "pipeline.yaml")

    # Merge MCP tool registry + retain sessions (ADR-028 D2 — fixes session-discard).
    # Graceful: unavailable servers are warned+skipped (skip_unavailable=True).
    from orchestrator.mcp.adapter import build_mcp_tool_registry_and_sessions_from_config

    mcp_tools, mcp_sessions = build_mcp_tool_registry_and_sessions_from_config(
        config_dir / "mcp_servers.yaml"
    )
    tools = {**tools, **mcp_tools}

    # Local tool registry — sandbox root defaults to config_dir parent (workspace).
    sandbox_root = config_dir.parent
    local_tools = build_local_tool_registry(sandbox_root)

    # Sandbox posture resolver (ADR-037 D4 / A1-3; P4.3-5 / RW4): load config + detect runtime.
    # Delegated to _resolve_sandbox_posture so tests can exercise the real branch without
    # re-implementing it (constitution RW8-2 wired-whole; this is the sole injection point).
    _sandbox_posture_resolver = _resolve_sandbox_posture(config_dir)

    # Plugin aggregation pass (ADR-029 D2 / P3.5-5 / ADR-038 D1/D2 P4.4-4): discover + validate
    # + merge all valid plugins from plugins/ (operator-placed) and fetched_plugins/ (fetched).
    # Absent plugins/ → no-op. Any-stage plugin failure refuses only that plugin.
    # Plugin registry: absent → defaults; malformed → REGISTRY_REFUSE_ALL sentinel → refuse-all.
    from orchestrator.core.room import RoomType as _RoomType
    from orchestrator.plugins.loader import load_plugins
    from orchestrator.plugins.schema import PLUGIN_HOST_CONTRACT_VERSION

    _plugin_registry = _resolve_plugin_registry(config_dir)

    plugin_result = load_plugins(
        sandbox_root / "plugins",
        models=llm_layer.models,
        host_room_types=frozenset(rt.value for rt in _RoomType),
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents=agents,
        host_skills=skills,
        host_tools=tools,
        host_local_tool_names=frozenset(local_tools.keys()),
        host_mcp_server_names=frozenset(mcp_sessions.keys()),
        fetched_plugins_dir=sandbox_root / "fetched_plugins",
        plugin_registry=_plugin_registry,
        posture_resolver=_sandbox_posture_resolver,
        sandbox_root=sandbox_root,
    )
    # Atomic per-plugin merge: plugin contributions that passed all stages are
    # merged here; partial or refused plugins leave no trace in these registries.
    agents = {**agents, **plugin_result.agents}
    regex_registry = {**regex_registry, **plugin_result.regex_registry}
    skills = {**skills, **plugin_result.skills}
    tools = {**tools, **plugin_result.tools}
    local_tools = {**local_tools, **plugin_result.local_tools}
    mcp_sessions = {**mcp_sessions, **plugin_result.mcp_sessions}

    # Subprocess local tools (ADR-034 D5 / P4.2-B3-3; ADR-037 D2/D3 P4.3-6): compose at
    # the api/ root so local.py stays in-process-pristine (constitution t6).
    from orchestrator.tools.subprocess_tools import build_subprocess_tool_registry

    local_tools = {
        **local_tools,
        **build_subprocess_tool_registry(sandbox_root, posture_resolver=_sandbox_posture_resolver),
    }

    # Network local tools (ADR-035 D4 / P4.2-B4-4 + B5-2): compose at the api/ root
    # so local.py stays in-process-pristine (constitution t6).
    # web_search provider config loaded once at bootstrap; absent → fail-closed (not configured).
    # send_email provider config loaded similarly; absent → fail-closed (not configured).
    from orchestrator.tools.network_tools import build_network_tool_registry

    _web_search_config = config_dir / "web_search.yaml"
    _email_config = config_dir / "email.yaml"
    local_tools = {
        **local_tools,
        **build_network_tool_registry(
            web_search_config_path=_web_search_config if _web_search_config.exists() else None,
            email_config_path=_email_config if _email_config.exists() else None,
            posture_resolver=_sandbox_posture_resolver,
            sandbox_root=sandbox_root,
        ),
    }

    # Mutation local tools (ADR-036 D4 / P4.2-B5-4): apply_edit in-process, sandboxed.
    # send_email / git_push auto-registered via network/subprocess registries above.
    from orchestrator.tools.mutation_tools import build_mutation_tool_registry

    local_tools = {**local_tools, **build_mutation_tool_registry(sandbox_root)}

    from orchestrator.api.llm_adapter import RealLLMRouter

    llm_router: LLMRouterProtocol = RealLLMRouter(
        agent_configs=llm_layer.agent_configs,
        models=llm_layer.models,
        providers=llm_layer.providers,
        override=llm_layer.override,
    )

    return AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=writer_executor,
        reader_executor=reader_executor,
        bus=bus,
        available_agents=agents,
        available_skills=skills,
        regex_registry=regex_registry,
        tools=tools,
        llm_router=llm_router,
        mcp_sessions=mcp_sessions,
        local_tools=local_tools,
        sandbox_root=sandbox_root,
        reader_local=_reader_local,
        reader_conns=_reader_conns,
        countdown_auto_fire=countdown_auto_fire_cfg,
        pipeline_scheduler=pipeline_scheduler_cfg,
        config_dir=config_dir,
    )


def _derive_provenance_and_kind(
    plugin_id: str,
    sandbox_root: Path,
    *,
    source_url: str | None,
    digest: str | None,
) -> tuple[str, str | None]:
    """Derive (provenance, provenance_kind) for a registry entry from filesystem roots.

    G3 absorb (R0-A-on-plan): entries in neither root are reported as
    declared-not-yet-on-disk; kind is inferred from the fetched-indicator
    (source_url+digest present -> fetched intent; absent -> operator-placed intent).
    """
    if (sandbox_root / "plugins" / plugin_id).exists():
        return "operator_placed", None
    if (sandbox_root / "fetched_plugins" / plugin_id).exists():
        return "fetched", None
    kind = "fetched (pending)" if (source_url and digest) else "operator-placed (pending)"
    return "declared-not-yet-on-disk", kind


def _register_routes(app: FastAPI, ctx: AppContext) -> None:
    """Register all API routes on the app with captured context.

    P3.2-2: read handlers (create/GET rooms, events, snapshot, thread).
    P3.2-3: WS live stream.
    P3.2-4: POST /intent write path.
    P4.5-3: /login + /logout endpoints.
    """

    # -----------------------------------------------------------------------
    # POST /login — credential verify → session create → HttpOnly cookie
    # POST /logout — revoke session + clear cookie
    # (ADR-039 D3/D4 — public endpoints, exempt from auth middleware)
    # -----------------------------------------------------------------------

    @app.post("/login", response_model=_LoginResponse)
    async def _login(body: _LoginRequest, request: Request) -> JSONResponse:
        from orchestrator.api.auth.session import create_session
        from orchestrator.api.auth.users import verify_password

        loop = asyncio.get_running_loop()

        # Verify on reader connection (read-only, non-blocking)
        ok = await loop.run_in_executor(
            ctx.reader_executor,
            lambda: verify_password(ctx.get_reader_conn(), body.user_id, body.password),
        )
        if not ok:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # Create session on writer connection (ADR-025 D6 / ADR-039 D3)
        session_id = await loop.run_in_executor(
            ctx.writer_executor,
            lambda: create_session(ctx.writer_store.conn, body.user_id),
        )

        resp = JSONResponse({"user_id": body.user_id})
        # HttpOnly + Secure + SameSite=Strict (ADR-039 D3, same-origin deployment A-2)
        resp.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=86400,
        )
        return resp

    @app.post("/logout", response_model=_LogoutResponse)
    async def _logout(request: Request) -> JSONResponse:
        from orchestrator.api.auth.session import revoke_sessions_for_user

        # principal guaranteed non-None by auth middleware (not in PUBLIC_PATHS)
        principal = request.state.principal
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            ctx.writer_executor,
            lambda: revoke_sessions_for_user(ctx.writer_store.conn, principal.user_id),
        )
        resp = JSONResponse({"status": "ok"})
        resp.delete_cookie("session_id")
        return resp

    @app.post("/rooms", response_model=Room, status_code=201)
    async def _create_room(body: _CreateRoomBody) -> Room:
        room = _CoreRoom(id=generate_room_id(), type=body.type)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(ctx.writer_executor, ctx.writer_store.append_room, room)
        return room

    @app.get("/rooms", response_model=list[Room])
    async def _list_rooms() -> list[Room]:
        """List all rooms ordered by created_at ASC.

        Auth-protected by being outside PUBLIC_PATHS (fail-closed middleware).
        Enumeration is an RB-AUTHZ read-surface instance — see ADR-039 D10.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            ctx.reader_executor,
            lambda: ctx.get_reader_store().list_rooms(),
        )

    @app.get("/rooms/{room_id}", response_model=Room)
    async def _get_room(room_id: str) -> Room:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.reader_executor,
            lambda: ctx.get_reader_store().get_room(RoomId(room_id)),
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"room {room_id!r} not found")
        return result

    @app.get("/rooms/{room_id}/events", response_model=list[Event])
    async def _get_room_events(room_id: str) -> list[Event]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            ctx.reader_executor,
            lambda: ctx.get_reader_store().get_room_events(RoomId(room_id)),
        )

    @app.get("/rooms/{room_id}/snapshot", response_model=Snapshot)
    async def _get_snapshot(room_id: str) -> Snapshot:
        loop = asyncio.get_running_loop()
        room, events = await asyncio.gather(
            loop.run_in_executor(
                ctx.reader_executor,
                lambda: ctx.get_reader_store().get_room(RoomId(room_id)),
            ),
            loop.run_in_executor(
                ctx.reader_executor,
                lambda: ctx.get_reader_store().get_room_events(RoomId(room_id)),
            ),
        )
        if room is None:
            raise HTTPException(status_code=404, detail=f"room {room_id!r} not found")
        return produce_snapshot(events, room, snapshot_at=now_ms())

    @app.get("/events/{event_id}/thread", response_model=list[Event])
    async def _get_thread(event_id: str) -> list[Event]:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                ctx.reader_executor,
                lambda: ctx.get_reader_store().get_thread(EventId(event_id)),
            )
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"event {event_id!r} not found") from exc

    @app.post(
        "/rooms/{room_id}/intent",
        response_model=IntentResponse,
        responses={422: {"model": IntentError}, 500: {"model": IntentError}},
    )
    async def _post_intent(room_id: str, body: IntentRequest, request: Request) -> IntentResponse:
        """Write path: forge-check → append → run_turn → cursor-diff → publish.

        Security spine (ADR-025 D4 / ADR-039 D1/D7):
          - author stamped server-side from the verified principal (P4.5-3)
          - id + timestamp server-stamped
          - type allowlist enforced before any append (fail-closed)
          - metadata validated by validate_metadata (shape-only, not authority)
        Error semantics (ADR-025 D5, R0-B Y3):
          - append-fail → _AppendFailedError → 422 IntentError{stage:"append"}
          - turn-fail  → _TurnFailedError  → 500 IntentError{stage:"turn"}
        """
        from orchestrator.api.wire import INTENT_TYPE_ALLOWLIST
        from orchestrator.rooms.runtime import run_turn

        rid = RoomId(room_id)

        # Payload size guard (D7 trust boundary)
        if len(body.model_dump_json().encode()) > PAYLOAD_LIMIT_BYTES:
            raise HTTPException(status_code=422, detail="payload exceeds size limit")

        # Forge-prevention: allowlist check (D4a) — before any I/O
        if body.type not in INTENT_TYPE_ALLOWLIST:
            raise HTTPException(
                status_code=422,
                detail=f"type {body.type!r} not in intent allowlist",
            )

        # Forge-prevention: metadata shape validation (D4) — before any I/O
        try:
            validated_meta = validate_metadata(body.type, body.metadata)
        except MetadataValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Server-stamp: author/id/timestamp — client cannot set these (D4/D7)
        # ADR-039 D1/D7: author stamped from the verified principal (P4.5-3),
        # never from the request body. principal is on request.state after auth.
        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"
        _author = build_user_author(_principal.user_id)
        user_event = Event(
            id=generate_event_id(),
            parent_id=body.parent_id,
            room_id=rid,
            type=body.type,
            author=_author,  # server-derived from principal — never from request
            timestamp=now_ms(),
            content=body.content,
            metadata=validated_meta,
        )

        loop = asyncio.get_running_loop()

        def _write_and_turn() -> IntentResponse:
            from orchestrator.agents.dispatch import dispatch_turn
            from orchestrator.rooms.runtime import select_dispatch_agents

            room = ctx.writer_store.get_room(rid)
            if room is None:
                raise _AppendFailedError(f"room {room_id!r} not found")

            pre_cursor = len(ctx.writer_store.get_room_events(rid))

            try:
                ctx.writer_store.append(user_event)
            except (RoomNotFoundError, InvalidParentError, MetadataValidationError) as exc:
                raise _AppendFailedError(str(exc)) from exc

            # Wall-clock deadline: stamp before pass 0 (ADR-033 D3 condition 4 / D4).
            loop_start = time.monotonic()

            # Mark cursor just after user_event append (before pass 0 dispatch+execute).
            # The re-dispatch loop checks what the PREVIOUS pass produced starting here.
            prev_pass_cursor = len(ctx.writer_store.get_room_events(rid))

            # Pass 0: state machine once + dispatch + execute (ADR-033 D2).
            try:
                turn_result = run_turn(
                    room,
                    user_event,
                    available_agents=ctx.available_agents,
                    available_skills=ctx.available_skills,
                    event_store=ctx.writer_store,
                    llm_router=ctx.llm_router,
                    regex_registry=ctx.regex_registry,
                    tools=ctx.tools,
                    countdown_auto_fire=ctx.countdown_auto_fire,
                )
            except Exception as exc:
                raise _TurnFailedError(str(exc), user_event.id) from exc

            # Post-dispatch execution stage for pass 0 (ADR-028 D1).
            pass0_window = ctx.writer_store.get_room_events(rid)[prev_pass_cursor:]
            execute_pending_tool_calls(
                window_events=pass0_window,
                room_id=rid,
                event_store=ctx.writer_store,
                mcp_sessions=ctx.mcp_sessions,
                local_tools=ctx.local_tools,
                llm_router=ctx.llm_router,
            )

            # Re-dispatch loop passes 1…N (ADR-033 D1/D2/D3).
            # Filter agents once — single source of truth (D2).
            filtered_agents = select_dispatch_agents(room, ctx.available_agents)
            _result_types = frozenset(
                {EventType.TOOL_RESULT, EventType.TOOL_FAILED, EventType.OBSERVATION}
            )

            for _pass in range(MAX_TURN_LOOP_PASSES):
                # Termination condition 4: re-dispatch overhead deadline (D3 / D4).
                # Caps time spent on passes 1…N; pass 0 is not constrained by this.
                if time.monotonic() - loop_start >= MAX_REDISPATCH_WALL_CLOCK_S:
                    break

                # Check what the previous pass produced (from prev_pass_cursor to now).
                prev_pass_events = ctx.writer_store.get_room_events(rid)[prev_pass_cursor:]

                # Termination condition 1: zero new TOOL_CALL events in last pass (D3).
                new_tool_calls = [e for e in prev_pass_events if e.type == EventType.TOOL_CALL]
                if not new_tool_calls:
                    break

                # Termination condition 2: no new result-class event to pass as current_event.
                result_events = [e for e in prev_pass_events if e.type in _result_types]
                if not result_events:
                    break

                # current_event for this re-dispatch pass = last result-class event (D2).
                current_event_for_pass = result_events[-1]

                # Advance cursor to start of THIS pass (before dispatch+execute).
                prev_pass_cursor = len(ctx.writer_store.get_room_events(rid))

                # Re-dispatch: call dispatch_turn directly (state machine NOT re-run — D2).
                dispatch_turn(
                    filtered_agents,
                    room,
                    current_event_for_pass,
                    event_store=ctx.writer_store,
                    llm_router=ctx.llm_router,
                    available_skills=ctx.available_skills,
                    regex_registry=ctx.regex_registry,
                    tools=ctx.tools,
                    countdown_auto_fire=ctx.countdown_auto_fire,
                )

                # Execute TOOL_CALL events from this re-dispatch pass.
                repass_window = ctx.writer_store.get_room_events(rid)[prev_pass_cursor:]
                execute_pending_tool_calls(
                    window_events=repass_window,
                    room_id=rid,
                    event_store=ctx.writer_store,
                    mcp_sessions=ctx.mcp_sessions,
                    local_tools=ctx.local_tools,
                    llm_router=ctx.llm_router,
                )

            # Publish all events accumulated since the user_event append (one batch).
            new_events = ctx.writer_store.get_room_events(rid)[pre_cursor:]
            loop.call_soon_threadsafe(ctx.bus.publish, rid, new_events)

            return IntentResponse(appended_event=user_event, turn=turn_result)

        return await loop.run_in_executor(ctx.writer_executor, _write_and_turn)

    # ---------------------------------------------------------------------------
    # POST /rooms/{room_id}/confirm — human-in-the-loop gating approval (ADR-030 D3)
    # ---------------------------------------------------------------------------

    @app.post(
        "/rooms/{room_id}/confirm",
        response_model=ConfirmResponse,
        responses={422: {"model": ConfirmError}, 500: {"model": ConfirmError}},
    )
    async def _post_confirm(
        room_id: str, body: ConfirmRequest, request: Request
    ) -> ConfirmResponse:
        """Confirm or cancel a pending gated tool call (ADR-030 D3).

        Handler logic (backend-authoritative, atomic on writer_executor):
        1. Resolve room; find the TOOL_CALL_PENDING by pending_event_id.
        2. Room-state gate: closed room → ConfirmError{stage:'append', reason:'room_closed'}.
        3. Still-pending check (layer 1) — position-anchored after the pending event.
        4. cancel → append TOOL_CALL_CANCELLED (with approver_user_id from principal).
        5. approve → append agent-authored TOOL_CALL from record (with approver_user_id).

        No decision surface: gate decision already made; human approval second factor only.
        ADR-039 D6: approver provenance recorded from the authenticated principal.
        D5 checkpoint seam #1: authenticated ⇒ allowed; role check would gate here.
        """
        rid = RoomId(room_id)
        loop = asyncio.get_running_loop()
        # ADR-039 D6: approver_user_id from server-verified principal (NOT request body)
        _confirm_principal = getattr(request.state, "principal", None)
        _approver_user_id: str | None = (
            _confirm_principal.user_id if _confirm_principal is not None else None
        )

        def _confirm_on_writer() -> ConfirmResponse:
            if body.decision == "cancel":
                # Cancel path: steps 1-4 inline (cancel branch not shared with sweeper).
                room = ctx.writer_store.get_room(rid)
                if room is None:
                    raise _ConfirmAppendError("not_found")
                if room.state == "closed":
                    raise _ConfirmAppendError("room_closed")

                all_events = ctx.writer_store.get_room_events(rid)
                sorted_events = sorted(all_events, key=lambda e: (e.timestamp, e.id))
                pending_event = next(
                    (
                        e
                        for e in sorted_events
                        if e.id == body.pending_event_id and e.type == EventType.TOOL_CALL_PENDING
                    ),
                    None,
                )
                if pending_event is None:
                    raise _ConfirmAppendError("not_found")

                pending_meta = ToolCallPendingMeta.model_validate(pending_event.metadata)
                pending_idx = sorted_events.index(pending_event)
                already_resolved = any(
                    later.type in PENDING_RESOLUTION_TYPES
                    and str(later.metadata.get("call_id", "")) == pending_meta.call_id
                    for later in sorted_events[pending_idx + 1 :]
                )
                if already_resolved:
                    raise _ConfirmAppendError("already_resolved")

                pre_cursor = len(all_events)
                # Step 4: Cancel — append TOOL_CALL_CANCELLED, done.
                cancelled_event = Event(
                    id=generate_event_id(),
                    room_id=rid,
                    type=EventType.TOOL_CALL_CANCELLED,
                    author=build_author(pending_meta.initiating_agent),
                    timestamp=now_ms(),
                    content="",
                    metadata=ToolCallCancelledMeta(
                        call_id=pending_meta.call_id,
                        approver_user_id=_approver_user_id,  # ADR-039 D6
                    ).model_dump(),
                )
                try:
                    ctx.writer_store.append(cancelled_event)
                except (RoomNotFoundError, InvalidParentError, MetadataValidationError) as exc:
                    raise _ConfirmAppendError(str(exc)) from exc

                new_events = ctx.writer_store.get_room_events(rid)[pre_cursor:]
                loop.call_soon_threadsafe(ctx.bus.publish, rid, new_events)
                return ConfirmResponse(appended_event=cancelled_event, turn_events=new_events)

            # Approve path: delegate to shared writer helper (ADR-040 D3).
            # The helper re-checks room-state + still-pending (guards must be inside — the
            # sweeper uses the same helper after a stale reader discovery pass).
            result = _writer_approve_helper(
                ctx, rid, body.pending_event_id, "human", _approver_user_id, loop
            )
            if isinstance(result, _ApproveOk):
                return ConfirmResponse(
                    appended_event=result.appended_event,
                    turn_events=result.turn_events,
                )
            if isinstance(result, _ApproveSkipped):
                raise _ConfirmAppendError(result.reason)
            raise _ConfirmExecuteError(result.reason, result.event_id)

        return await loop.run_in_executor(ctx.writer_executor, _confirm_on_writer)

    # ---------------------------------------------------------------------------
    # Plugin management routes — GET + enable/disable/admit/DELETE (ADR-038 D5)
    #
    # Boot-only: all writes mutate config/plugins.yaml and respond with
    # effect:next_restart.  Zero live AppContext mutation (ADR-038 D2 / DP1a).
    # Not in PUBLIC_PATHS → fail-closed auth inherited from middleware (ADR-039 D4).
    # Principal read from request.state (server-derived, never body — ADR-039 D7).
    # ---------------------------------------------------------------------------

    @app.get("/plugins", response_model=list[_PluginInfo])
    async def _get_plugins() -> list[_PluginInfo]:
        """List declared plugin registry entries (id/provenance/enabled/version/fetched).

        Runs on ctx.reader_executor (G2 absorb, R0-A-on-plan).
        last-load-result column deferred as named residual (Y1=(a), ADR-038 D5 T5).
        """
        from orchestrator.plugins.provenance import load_plugin_registry

        loop = asyncio.get_running_loop()

        def _read() -> list[_PluginInfo]:
            registry = load_plugin_registry(ctx.config_dir / "plugins.yaml")
            result: list[_PluginInfo] = []
            for pid, entry in registry.items():
                provenance, provenance_kind = _derive_provenance_and_kind(
                    pid,
                    ctx.sandbox_root,
                    source_url=entry.source_url,
                    digest=entry.digest,
                )
                result.append(
                    _PluginInfo(
                        plugin_id=pid,
                        enabled=entry.enabled,
                        version=entry.version,
                        provenance=provenance,
                        provenance_kind=provenance_kind,
                        fetched=bool(entry.source_url and entry.digest),
                    )
                )
            return result

        return await loop.run_in_executor(ctx.reader_executor, _read)

    @app.post("/plugins/{plugin_id}/enable", response_model=_PluginWriteResponse)
    async def _enable_plugin(plugin_id: str, request: Request) -> _PluginWriteResponse:
        # ADR-039 D5 checkpoint seam #2: authenticated ⇒ allowed; role check (DP3b) would gate here.
        _principal = request.state.principal  # ADR-039 D7: server-derived, never body
        from orchestrator.plugins.provenance import (
            RegistryEntry,
            load_plugin_registry,
            write_plugin_registry,
        )

        loop = asyncio.get_running_loop()

        def _write() -> _PluginWriteResponse:
            registry_path = ctx.config_dir / "plugins.yaml"
            registry = load_plugin_registry(registry_path)
            existing = registry.get(plugin_id)
            registry[plugin_id] = RegistryEntry(
                plugin_id=plugin_id,
                enabled=True,
                version=existing.version if existing else None,
                source_url=existing.source_url if existing else None,
                digest=existing.digest if existing else None,
                plugin_subprocess_env=existing.plugin_subprocess_env if existing else {},
            )
            write_plugin_registry(registry_path, registry)
            return _PluginWriteResponse()

        return await loop.run_in_executor(ctx.writer_executor, _write)

    @app.post("/plugins/{plugin_id}/disable", response_model=_PluginWriteResponse)
    async def _disable_plugin(plugin_id: str, request: Request) -> _PluginWriteResponse:
        # ADR-039 D5 checkpoint seam #2: authenticated ⇒ allowed; role check (DP3b) would gate here.
        _principal = request.state.principal  # ADR-039 D7: server-derived, never body
        from orchestrator.plugins.provenance import (
            RegistryEntry,
            load_plugin_registry,
            write_plugin_registry,
        )

        loop = asyncio.get_running_loop()

        def _write() -> _PluginWriteResponse:
            registry_path = ctx.config_dir / "plugins.yaml"
            registry = load_plugin_registry(registry_path)
            existing = registry.get(plugin_id)
            registry[plugin_id] = RegistryEntry(
                plugin_id=plugin_id,
                enabled=False,
                version=existing.version if existing else None,
                source_url=existing.source_url if existing else None,
                digest=existing.digest if existing else None,
                plugin_subprocess_env=existing.plugin_subprocess_env if existing else {},
            )
            write_plugin_registry(registry_path, registry)
            return _PluginWriteResponse()

        return await loop.run_in_executor(ctx.writer_executor, _write)

    @app.post("/plugins/{plugin_id}/admit", response_model=_PluginWriteResponse)
    async def _admit_plugin(
        plugin_id: str, body: _AdmitRequest, request: Request
    ) -> _PluginWriteResponse:
        # seam #2-admit: admit introduces new fetched code into the trust boundary —
        # strictly higher-trust than enable/disable toggling already-vetted code; a
        # future DP3b may gate who-may-admit stricter than who-may-toggle (ADR-039 D5).
        #
        # No fetch_plugin_bundle call here: admit authors operator intent only.
        # Fetch is out-of-band (ADR-038 D2 fetch≠admit; DP1-i author-entry-only).
        # The digest-before-extract gauntlet (fetch.py:121) is unchanged + mandatory
        # at the separate fetch step (ADR-031 D5 / DP3a byte-frozen).
        _principal = request.state.principal  # ADR-039 D7: server-derived, never body
        from orchestrator.plugins.provenance import (
            RegistryEntry,
            load_plugin_registry,
            write_plugin_registry,
        )

        loop = asyncio.get_running_loop()

        def _write() -> _PluginWriteResponse:
            registry_path = ctx.config_dir / "plugins.yaml"
            registry = load_plugin_registry(registry_path)
            existing = registry.get(plugin_id)
            registry[plugin_id] = RegistryEntry(
                plugin_id=plugin_id,
                enabled=existing.enabled if existing else True,
                version=body.version,
                source_url=body.source_url,
                digest=body.digest,
                plugin_subprocess_env=existing.plugin_subprocess_env if existing else {},
            )
            write_plugin_registry(registry_path, registry)
            return _PluginWriteResponse()

        return await loop.run_in_executor(ctx.writer_executor, _write)

    @app.delete("/plugins/{plugin_id}", response_model=_PluginWriteResponse)
    async def _delete_plugin(plugin_id: str, request: Request) -> _PluginWriteResponse:
        # ADR-039 D5 checkpoint seam #2: authenticated ⇒ allowed; role check (DP3b) would gate here.
        _principal = request.state.principal  # ADR-039 D7: server-derived, never body
        from orchestrator.plugins.provenance import load_plugin_registry, write_plugin_registry

        loop = asyncio.get_running_loop()

        def _write() -> bool:
            registry_path = ctx.config_dir / "plugins.yaml"
            registry = load_plugin_registry(registry_path)
            if plugin_id not in registry:
                return False
            del registry[plugin_id]
            write_plugin_registry(registry_path, registry)
            return True

        found = await loop.run_in_executor(ctx.writer_executor, _write)
        if not found:
            raise HTTPException(status_code=404, detail=f"plugin {plugin_id!r} not in registry")
        return _PluginWriteResponse()

    @app.exception_handler(_ConfirmAppendError)
    async def _confirm_append_failed_handler(
        request: Request, exc: _ConfirmAppendError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ConfirmError(
                stage="append", appended_event_id=None, reason=exc.reason
            ).model_dump(),
        )

    @app.exception_handler(_ConfirmExecuteError)
    async def _confirm_execute_failed_handler(
        request: Request, exc: _ConfirmExecuteError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=ConfirmError(
                stage="execute", appended_event_id=exc.event_id, reason=exc.reason
            ).model_dump(),
        )

    # ---------------------------------------------------------------------------
    # Exception handlers for the partial-turn error envelope (ADR-025 D5)
    # ---------------------------------------------------------------------------

    @app.exception_handler(_AppendFailedError)
    async def _append_failed_handler(request: Request, exc: _AppendFailedError) -> JSONResponse:
        from orchestrator.api.wire import IntentError

        return JSONResponse(
            status_code=422,
            content=IntentError(
                stage="append", appended_event_id=None, reason=exc.reason
            ).model_dump(),
        )

    @app.exception_handler(_TurnFailedError)
    async def _turn_failed_handler(request: Request, exc: _TurnFailedError) -> JSONResponse:
        from orchestrator.api.wire import IntentError

        return JSONResponse(
            status_code=500,
            content=IntentError(
                stage="turn", appended_event_id=exc.event_id, reason=exc.reason
            ).model_dump(),
        )

    @app.websocket("/rooms/{room_id}/stream")
    async def _room_stream(websocket: WebSocket, room_id: str) -> None:
        """Subscribe-then-replay+dedup WS stream (ADR-025 D6, R0-B Y1).

        Order: (1) subscribe → queue captures all events from now;
               (2) replay current events from reader conn;
               (3) send replay_complete sentinel;
               (4) drain queue, skipping ids already sent in replay (dedup).
        This order guarantees no event is lost between replay and live stream.

        ADR-039 D4: WS auth check is in-handler, BEFORE websocket.accept().
        BaseHTTPMiddleware does not see WS scopes, so this is necessary and
        not redundant with the HTTP auth middleware (absorbed A-1/M3).
        An unauthenticated upgrade is rejected without calling accept()
        (accept-then-close leaves a half-open-stream window).
        """
        from starlette.websockets import WebSocketDisconnect

        from orchestrator.api.auth.session import validate_session, validate_token
        from orchestrator.api.wire import StreamEventMessage, StreamReplayCompleteMessage

        # --- WS auth: resolve principal before accept() (ADR-039 D4) ---
        # Each lambda runs on a reader_executor worker thread and calls
        # ctx.get_reader_conn() to get that thread's own SQLite connection,
        # eliminating the shared-connection race fixed in RW7.
        loop = asyncio.get_running_loop()
        principal = None

        # Try session cookie (browsers send cookies on WS upgrade)
        try:
            ws_session_id = websocket.cookies.get("session_id")
            if ws_session_id:
                principal = await loop.run_in_executor(
                    ctx.reader_executor,
                    lambda: validate_session(ctx.get_reader_conn(), ws_session_id),
                )

            # Try Bearer token in query param (programmatic clients)
            if principal is None:
                ws_token = websocket.query_params.get("token")
                if ws_token:
                    principal = await loop.run_in_executor(
                        ctx.reader_executor,
                        lambda: validate_token(ctx.get_reader_conn(), ws_token),
                    )

            # Try Authorization: Bearer header (programmatic clients via header)
            if principal is None:
                auth_hdr = websocket.headers.get("Authorization", "")
                if auth_hdr.startswith("Bearer "):
                    raw_token = auth_hdr[7:]
                    principal = await loop.run_in_executor(
                        ctx.reader_executor,
                        lambda: validate_token(ctx.get_reader_conn(), raw_token),
                    )
        except Exception:
            # Auth executor raised — close cleanly so client is never left hanging.
            with suppress(Exception):
                await websocket.close(code=1011)  # 1011 = Internal Error
            return

        if principal is None:
            # Reject BEFORE accept() — no half-open-stream window
            await websocket.close(code=1008)  # 1008 = Policy Violation
            return

        # Store principal on websocket state for handlers (mirroring HTTP middleware)
        websocket.state.principal = principal

        await websocket.accept()
        rid = RoomId(room_id)
        loop = asyncio.get_running_loop()

        # (1) Subscribe FIRST — every event published from this instant is queued.
        q = ctx.bus.subscribe(rid)
        sent_ids: set[str] = set()

        try:
            # (2) Replay current events from the read-only reader connection.
            replay_events = await loop.run_in_executor(
                ctx.reader_executor,
                lambda: ctx.get_reader_store().get_room_events(rid),
            )
            for event in replay_events:
                await websocket.send_text(StreamEventMessage(event=event).model_dump_json())
                sent_ids.add(event.id)

            # (3) Replay-complete sentinel — client knows history is done.
            await websocket.send_text(StreamReplayCompleteMessage().model_dump_json())

            # (4) Live stream — dedup any event already sent in replay.
            keepalive_s = 30.0
            while True:
                try:
                    live_event = await asyncio.wait_for(q.get(), timeout=keepalive_s)
                except TimeoutError:
                    try:
                        await websocket.send_text('{"kind":"ping"}')
                    except Exception:
                        break
                    continue
                if live_event.id not in sent_ids:
                    await websocket.send_text(
                        StreamEventMessage(event=live_event).model_dump_json()
                    )
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            ctx.bus.unsubscribe(rid, q)

    # ---------------------------------------------------------------------------
    # Pipeline CRUD + manual trigger (ADR-041 D7/D8 / T5)
    # All routes: owner-private, fail-closed auth (non-owner → 403).
    # principal is server-derived from request.state (ADR-039 D1 — never from body).
    # ---------------------------------------------------------------------------

    @app.post("/pipelines", response_model=_PipelineResponse, status_code=201)
    async def _create_pipeline(body: _PipelineCreateRequest, request: Request) -> _PipelineResponse:
        """Create a new pipeline definition. owner_user_id captured from principal."""
        from orchestrator.pipeline.schema import OutputConfig, PipelineDefinition
        from orchestrator.pipeline.store import create_pipeline
        from orchestrator.sources.schema import Source

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        try:
            sources = [Source.model_validate(s) for s in body.sources]
            output_config = (
                OutputConfig.model_validate(body.output_config)
                if body.output_config
                else OutputConfig()
            )
            defn = PipelineDefinition(
                sources=sources,
                analysis_prompts=body.analysis_prompts,
                output_config=output_config,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid pipeline definition: {exc}"
            ) from exc

        loop = asyncio.get_running_loop()

        def _write() -> _PipelineResponse:
            record = create_pipeline(
                ctx.writer_store.conn,
                owner_user_id=_principal.user_id,
                definition=defn,
            )
            return _PipelineResponse(
                pipeline_id=record.pipeline_id,
                owner_user_id=record.owner_user_id,
                enabled=record.enabled,
                created_at=record.created_at,
                sources=[s.model_dump() for s in record.definition.sources],
                analysis_prompts=record.definition.analysis_prompts,
                output_config=record.definition.output_config.model_dump(),
            )

        return await loop.run_in_executor(ctx.writer_executor, _write)

    @app.get("/pipelines", response_model=list[_PipelineResponse])
    async def _list_pipelines(request: Request) -> list[_PipelineResponse]:
        """List pipelines owned by the current principal (owner-private)."""
        from orchestrator.pipeline.store import list_pipelines

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        loop = asyncio.get_running_loop()

        def _read() -> list[_PipelineResponse]:
            records = list_pipelines(ctx.get_reader_conn(), _principal.user_id)
            return [
                _PipelineResponse(
                    pipeline_id=r.pipeline_id,
                    owner_user_id=r.owner_user_id,
                    enabled=r.enabled,
                    created_at=r.created_at,
                    sources=[s.model_dump() for s in r.definition.sources],
                    analysis_prompts=r.definition.analysis_prompts,
                    output_config=r.definition.output_config.model_dump(),
                )
                for r in records
            ]

        return await loop.run_in_executor(ctx.reader_executor, _read)

    @app.get("/pipelines/{pipeline_id}", response_model=_PipelineResponse)
    async def _get_pipeline(pipeline_id: str, request: Request) -> _PipelineResponse:
        """Get a single pipeline definition (owner-private — 403 for non-owner)."""
        from orchestrator.pipeline.store import get_pipeline

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        loop = asyncio.get_running_loop()
        record = await loop.run_in_executor(
            ctx.reader_executor,
            lambda: get_pipeline(ctx.get_reader_conn(), pipeline_id),
        )
        if record is None:
            raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id!r} not found")
        if record.owner_user_id != _principal.user_id:
            raise HTTPException(status_code=403, detail="access denied: not the owner")
        return _PipelineResponse(
            pipeline_id=record.pipeline_id,
            owner_user_id=record.owner_user_id,
            enabled=record.enabled,
            created_at=record.created_at,
            sources=[s.model_dump() for s in record.definition.sources],
            analysis_prompts=record.definition.analysis_prompts,
            output_config=record.definition.output_config.model_dump(),
        )

    @app.post("/pipelines/{pipeline_id}/run", response_model=_PipelineRunResponse)
    async def _run_pipeline(pipeline_id: str, request: Request) -> _PipelineRunResponse:
        """Trigger a manual pipeline run (owner-private — 403 for non-owner).

        Runs synchronously on writer_executor (mirrors _write_and_turn).
        A pipeline_runs index row is written (T2).
        """
        from orchestrator.pipeline.runner import PipelineDeps, run_pipeline
        from orchestrator.pipeline.store import (
            create_pipeline_run,
            get_pipeline,
        )

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        loop = asyncio.get_running_loop()

        # Load definition on reader first (owner check)
        record = await loop.run_in_executor(
            ctx.reader_executor,
            lambda: get_pipeline(ctx.get_reader_conn(), pipeline_id),
        )
        if record is None:
            raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id!r} not found")
        if record.owner_user_id != _principal.user_id:
            raise HTTPException(status_code=403, detail="access denied: not the owner")

        definition = record.definition
        owner_user_id = _principal.user_id

        def _run_on_writer() -> _PipelineRunResponse:
            deps = PipelineDeps(
                writer_store=ctx.writer_store,
                llm_router=ctx.llm_router,
                tools=ctx.tools,
                mcp_sessions=ctx.mcp_sessions,
                local_tools=ctx.local_tools,
                sandbox_root=ctx.sandbox_root,
                bus=ctx.bus,
            )
            result = run_pipeline(
                pipeline_id,
                definition,
                deps=deps,
                owner_user_id=owner_user_id,
            )
            # Write pipeline_runs index row (T2).
            # Pass result.run_id so the store row id == the anchor event run_id
            # (single run_id across the runner/store boundary — F-runid).
            run_record = create_pipeline_run(
                ctx.writer_store.conn,
                pipeline_id=pipeline_id,
                room_id=result.room_id,
                owner_user_id=owner_user_id,
                run_id=result.run_id,
                status="completed" if result.succeeded else "failed",
            )
            return _PipelineRunResponse(
                run_id=run_record.run_id,
                room_id=result.room_id,
                pipeline_id=pipeline_id,
                succeeded=result.succeeded,
                sources_read=result.sources_read,
                branches_succeeded=result.branches_succeeded,
                branches_failed=result.branches_failed,
                summary=result.summary,
                error=result.error,
            )

        return await loop.run_in_executor(ctx.writer_executor, _run_on_writer)

    # ---------------------------------------------------------------------------
    # Schedule management endpoints (ADR-042 D9 / P5.1b-5)
    # All routes: owner-private (owner from parent pipeline), fail-closed auth.
    # principal derived server-side — never from the body (ADR-039 D1).
    # ---------------------------------------------------------------------------

    @app.post(
        "/pipelines/{pipeline_id}/schedules",
        response_model=_ScheduleResponse,
        status_code=201,
    )
    async def _create_schedule(
        pipeline_id: str, body: _ScheduleCreateRequest, request: Request
    ) -> _ScheduleResponse:
        """Create a schedule for a pipeline (owner-private; 403 for non-owner).

        ``kind=cron`` with a valid expression is accepted; malformed cron is rejected with 422.
        """
        from orchestrator.pipeline.schedule import (
            compute_next_fire,
            validate_schedule_expr,
        )
        from orchestrator.pipeline.store import (
            create_schedule,
            get_pipeline,
        )

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        loop = asyncio.get_running_loop()

        # Validate expr + kind before touching the DB; 422 on invalid or deferred.
        try:
            validate_schedule_expr(body.kind, body.expr)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Owner check on reader.
        pipeline = await loop.run_in_executor(
            ctx.reader_executor,
            lambda: get_pipeline(ctx.get_reader_conn(), pipeline_id),
        )
        if pipeline is None:
            raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id!r} not found")
        if pipeline.owner_user_id != _principal.user_id:
            raise HTTPException(status_code=403, detail="access denied: not the owner")

        def _write() -> _ScheduleResponse:
            initial_next_fire = compute_next_fire(body.kind, body.expr, now_ms())
            record = create_schedule(
                ctx.writer_store.conn,
                pipeline_id=pipeline_id,
                owner_user_id=_principal.user_id,
                kind=body.kind,
                expr=body.expr,
                next_fire=initial_next_fire,
            )
            return _ScheduleResponse(
                schedule_id=record.schedule_id,
                pipeline_id=record.pipeline_id,
                owner_user_id=record.owner_user_id,
                kind=record.kind,
                expr=record.expr,
                next_fire=record.next_fire,
                enabled=record.enabled,
                created_at=record.created_at,
                email_enabled=record.email_enabled,
                email_mode=record.email_mode,
                email_recipient=record.email_recipient,
            )

        return await loop.run_in_executor(ctx.writer_executor, _write)

    @app.get(
        "/pipelines/{pipeline_id}/schedules",
        response_model=list[_ScheduleResponse],
    )
    async def _list_schedules(pipeline_id: str, request: Request) -> list[_ScheduleResponse]:
        """List schedules for a pipeline (owner-private)."""
        from orchestrator.pipeline.store import get_pipeline, list_schedules_for_pipeline

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        loop = asyncio.get_running_loop()

        def _read() -> list[_ScheduleResponse]:
            pipeline = get_pipeline(ctx.get_reader_conn(), pipeline_id)
            if pipeline is None:
                raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id!r} not found")
            if pipeline.owner_user_id != _principal.user_id:
                raise HTTPException(status_code=403, detail="access denied: not the owner")
            records = list_schedules_for_pipeline(ctx.get_reader_conn(), pipeline_id)
            return [
                _ScheduleResponse(
                    schedule_id=r.schedule_id,
                    pipeline_id=r.pipeline_id,
                    owner_user_id=r.owner_user_id,
                    kind=r.kind,
                    expr=r.expr,
                    next_fire=r.next_fire,
                    enabled=r.enabled,
                    created_at=r.created_at,
                    email_enabled=r.email_enabled,
                    email_mode=r.email_mode,
                    email_recipient=r.email_recipient,
                )
                for r in records
            ]

        return await loop.run_in_executor(ctx.reader_executor, _read)

    @app.delete(
        "/pipelines/{pipeline_id}/schedules/{schedule_id}",
        status_code=204,
    )
    async def _delete_schedule(pipeline_id: str, schedule_id: str, request: Request) -> None:
        """Delete a schedule (owner-private)."""
        from orchestrator.pipeline.store import delete_schedule, get_pipeline, get_schedule

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        loop = asyncio.get_running_loop()

        def _write() -> None:
            pipeline = get_pipeline(ctx.writer_store.conn, pipeline_id)
            if pipeline is None:
                raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id!r} not found")
            if pipeline.owner_user_id != _principal.user_id:
                raise HTTPException(status_code=403, detail="access denied: not the owner")
            sched = get_schedule(ctx.writer_store.conn, schedule_id)
            if sched is None:
                raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
            if sched.pipeline_id != pipeline_id:
                raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
            delete_schedule(ctx.writer_store.conn, schedule_id)

        await loop.run_in_executor(ctx.writer_executor, _write)

    @app.patch(
        "/pipelines/{pipeline_id}/schedules/{schedule_id}",
        response_model=_ScheduleResponse,
    )
    async def _patch_schedule(
        pipeline_id: str,
        schedule_id: str,
        body: _ScheduleEnableRequest,
        request: Request,
    ) -> _ScheduleResponse:
        """Enable or disable a schedule (owner-private).

        On re-enable, recomputes next_fire from now so a long-disabled schedule
        does not fire immediately.
        """
        from orchestrator.pipeline.schedule import compute_next_fire
        from orchestrator.pipeline.store import (
            get_pipeline,
            get_schedule,
            set_schedule_enabled,
            update_schedule_next_fire,
        )

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        loop = asyncio.get_running_loop()

        def _write() -> _ScheduleResponse:
            pipeline = get_pipeline(ctx.writer_store.conn, pipeline_id)
            if pipeline is None:
                raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id!r} not found")
            if pipeline.owner_user_id != _principal.user_id:
                raise HTTPException(status_code=403, detail="access denied: not the owner")
            sched = get_schedule(ctx.writer_store.conn, schedule_id)
            if sched is None:
                raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
            if sched.pipeline_id != pipeline_id:
                raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
            set_schedule_enabled(ctx.writer_store.conn, schedule_id, body.enabled)
            # On re-enable: recompute next_fire from now (avoid immediate stale fire).
            if body.enabled:
                new_next_fire = compute_next_fire(sched.kind, sched.expr, now_ms())
                update_schedule_next_fire(ctx.writer_store.conn, schedule_id, new_next_fire)
            updated = get_schedule(ctx.writer_store.conn, schedule_id)
            assert updated is not None
            return _ScheduleResponse(
                schedule_id=updated.schedule_id,
                pipeline_id=updated.pipeline_id,
                owner_user_id=updated.owner_user_id,
                kind=updated.kind,
                expr=updated.expr,
                next_fire=updated.next_fire,
                enabled=updated.enabled,
                created_at=updated.created_at,
                email_enabled=updated.email_enabled,
                email_mode=updated.email_mode,
                email_recipient=updated.email_recipient,
            )

        return await loop.run_in_executor(ctx.writer_executor, _write)

    # -----------------------------------------------------------------------
    # P5.1c-2: email opt-in endpoints (owner-private, 3-state, ADR-043 D5/D6)
    # -----------------------------------------------------------------------

    @app.post(
        "/pipelines/{pipeline_id}/schedules/{schedule_id}/email-optin",
        response_model=_ScheduleResponse,
    )
    async def _schedule_email_optin(
        pipeline_id: str,
        schedule_id: str,
        body: _ScheduleEmailOptinRequest,
        request: Request,
    ) -> _ScheduleResponse:
        """Opt a schedule into headless email (→ dry-run state, owner-private, ADR-043 D5/D6)."""
        from orchestrator.pipeline.store import (
            get_pipeline,
            get_schedule,
            set_schedule_email_optin,
        )

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        loop = asyncio.get_running_loop()

        def _write() -> _ScheduleResponse:
            pipeline = get_pipeline(ctx.writer_store.conn, pipeline_id)
            if pipeline is None:
                raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id!r} not found")
            if pipeline.owner_user_id != _principal.user_id:
                raise HTTPException(status_code=403, detail="access denied: not the owner")
            sched = get_schedule(ctx.writer_store.conn, schedule_id)
            if sched is None:
                raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
            if sched.pipeline_id != pipeline_id:
                raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
            set_schedule_email_optin(
                ctx.writer_store.conn, schedule_id, recipient=body.email_recipient
            )
            updated = get_schedule(ctx.writer_store.conn, schedule_id)
            assert updated is not None
            return _ScheduleResponse(
                schedule_id=updated.schedule_id,
                pipeline_id=updated.pipeline_id,
                owner_user_id=updated.owner_user_id,
                kind=updated.kind,
                expr=updated.expr,
                next_fire=updated.next_fire,
                enabled=updated.enabled,
                created_at=updated.created_at,
                email_enabled=updated.email_enabled,
                email_mode=updated.email_mode,
                email_recipient=updated.email_recipient,
            )

        return await loop.run_in_executor(ctx.writer_executor, _write)

    @app.post(
        "/pipelines/{pipeline_id}/schedules/{schedule_id}/email-promote",
        response_model=_ScheduleResponse,
    )
    async def _schedule_email_promote(
        pipeline_id: str,
        schedule_id: str,
        request: Request,
    ) -> _ScheduleResponse:
        """Promote email opt-in dry-run → live (explicit second action, ADR-043 D6)."""
        from orchestrator.pipeline.store import (
            get_pipeline,
            get_schedule,
            promote_schedule_email_live,
        )

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        loop = asyncio.get_running_loop()

        def _write() -> _ScheduleResponse:
            pipeline = get_pipeline(ctx.writer_store.conn, pipeline_id)
            if pipeline is None:
                raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id!r} not found")
            if pipeline.owner_user_id != _principal.user_id:
                raise HTTPException(status_code=403, detail="access denied: not the owner")
            sched = get_schedule(ctx.writer_store.conn, schedule_id)
            if sched is None:
                raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
            if sched.pipeline_id != pipeline_id:
                raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
            if not sched.email_enabled:
                raise HTTPException(
                    status_code=409,
                    detail="cannot promote: email opt-in is OFF (call email-optin first)",
                )
            promote_schedule_email_live(ctx.writer_store.conn, schedule_id)
            updated = get_schedule(ctx.writer_store.conn, schedule_id)
            assert updated is not None
            return _ScheduleResponse(
                schedule_id=updated.schedule_id,
                pipeline_id=updated.pipeline_id,
                owner_user_id=updated.owner_user_id,
                kind=updated.kind,
                expr=updated.expr,
                next_fire=updated.next_fire,
                enabled=updated.enabled,
                created_at=updated.created_at,
                email_enabled=updated.email_enabled,
                email_mode=updated.email_mode,
                email_recipient=updated.email_recipient,
            )

        return await loop.run_in_executor(ctx.writer_executor, _write)

    @app.post(
        "/pipelines/{pipeline_id}/schedules/{schedule_id}/email-disable",
        response_model=_ScheduleResponse,
    )
    async def _schedule_email_disable(
        pipeline_id: str,
        schedule_id: str,
        request: Request,
    ) -> _ScheduleResponse:
        """Disable email opt-in for a schedule (→ OFF state, owner-private, ADR-043 D5)."""
        from orchestrator.pipeline.store import (
            disable_schedule_email,
            get_pipeline,
            get_schedule,
        )

        _principal = getattr(request.state, "principal", None)
        assert _principal is not None, "principal is None: auth middleware invariant violated"

        loop = asyncio.get_running_loop()

        def _write() -> _ScheduleResponse:
            pipeline = get_pipeline(ctx.writer_store.conn, pipeline_id)
            if pipeline is None:
                raise HTTPException(status_code=404, detail=f"pipeline {pipeline_id!r} not found")
            if pipeline.owner_user_id != _principal.user_id:
                raise HTTPException(status_code=403, detail="access denied: not the owner")
            sched = get_schedule(ctx.writer_store.conn, schedule_id)
            if sched is None:
                raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
            if sched.pipeline_id != pipeline_id:
                raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
            disable_schedule_email(ctx.writer_store.conn, schedule_id)
            updated = get_schedule(ctx.writer_store.conn, schedule_id)
            assert updated is not None
            return _ScheduleResponse(
                schedule_id=updated.schedule_id,
                pipeline_id=updated.pipeline_id,
                owner_user_id=updated.owner_user_id,
                kind=updated.kind,
                expr=updated.expr,
                next_fire=updated.next_fire,
                enabled=updated.enabled,
                created_at=updated.created_at,
                email_enabled=updated.email_enabled,
                email_mode=updated.email_mode,
                email_recipient=updated.email_recipient,
            )

        return await loop.run_in_executor(ctx.writer_executor, _write)


def _configure(app: FastAPI) -> None:
    """Construction-time configure step — registers auth middleware.

    Called by BOTH create_app AND _make_test_app so the fail-closed boundary
    is wired through the same production middleware the test suite exercises
    (the 37/37 _make_test_app tests walk through this path — ADR-039 D4 Y1).

    Middleware must be registered at construction, before app.state.ctx is set.
    The middleware reads request.app.state.ctx at request time (set in lifespan
    for create_app, or directly on app.state in _make_test_app).
    """
    from orchestrator.api.auth.middleware import AuthMiddleware

    app.add_middleware(AuthMiddleware)


def create_app(config_dir: Path, db_path: Path) -> FastAPI:
    """Production factory — builds context, registers routes, manages lifecycle.

    create_app(config_dir, db_path) is the single entry point for all
    production usage. Tests use _make_test_app(ctx) to inject a pre-built
    AppContext (bypassing the full bootstrap).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ctx = _build_context(config_dir, db_path)
        # Stow ctx on app.state so the auth middleware can read it at
        # request time without a closure (ADR-039 D4 Y1 absorption).
        app.state.ctx = ctx
        _register_routes(app, ctx)

        # Start COUNTDOWN sweeper if enabled (ADR-040 D1/D7 / P4.6-4).
        _sweeper_task: asyncio.Task[None] | None = None
        if ctx.countdown_auto_fire.enabled:
            _server_start_ms = now_ms()
            _loop = asyncio.get_running_loop()
            _sweeper_task = asyncio.create_task(
                _countdown_sweeper(ctx, ctx.countdown_auto_fire, _loop, _server_start_ms),
                name="countdown-sweeper",
            )

        # Start pipeline schedule sweeper if enabled (ADR-042 D1/D7 / P5.1b-4).
        _schedule_sweeper_task: asyncio.Task[None] | None = None
        if ctx.pipeline_scheduler.enabled:
            _loop = asyncio.get_running_loop()
            # Boot re-arm: advance past-due schedules without running (ADR-042 D5).
            await _loop.run_in_executor(ctx.writer_executor, lambda: _rearm_schedules_on_boot(ctx))
            _schedule_sweeper_task = asyncio.create_task(
                _schedule_sweeper(ctx, ctx.pipeline_scheduler, _loop),
                name="schedule-sweeper",
            )

        yield

        # Tear down sweepers before ctx.shutdown() (cancel cleanly, no pending-task warning).
        if _sweeper_task is not None:
            _sweeper_task.cancel()
            with suppress(asyncio.CancelledError):
                await _sweeper_task
        if _schedule_sweeper_task is not None:
            _schedule_sweeper_task.cancel()
            with suppress(asyncio.CancelledError):
                await _schedule_sweeper_task
        ctx.shutdown()

    app = FastAPI(
        title="Orchestrator API",
        version="0.1.0",
        description="HTTP/WS API over the event store and room runtime (ADR-025)",
        lifespan=lifespan,
    )
    _configure(app)
    return app


def _make_test_app(ctx: AppContext) -> FastAPI:
    """Test helper: creates an app with pre-built context (no lifespan bootstrap)."""
    app = FastAPI(title="Orchestrator API [test]", version="0.1.0")
    _configure(app)
    # Stow ctx on app.state immediately (no lifespan in tests — ADR-039 D4 Y1).
    app.state.ctx = ctx
    _register_routes(app, ctx)
    return app
