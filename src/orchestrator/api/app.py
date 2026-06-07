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
from pydantic import BaseModel, ConfigDict

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
from orchestrator.skills.loader import load_skills
from orchestrator.skills.schema import Skill
from orchestrator.tools.executor import LocalToolRegistry, execute_pending_tool_calls
from orchestrator.tools.local import build_local_tool_registry

if TYPE_CHECKING:
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
    countdown_auto_fire: CountdownAutoFireConfig = field(
        default_factory=CountdownAutoFireConfig
    )

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


def _writer_approve_helper(
    ctx: AppContext,
    rid: RoomId,
    pending_event_id: str,
    approval_source: Literal["human", "auto_timer"],
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
    countdown_auto_fire_cfg = load_countdown_auto_fire_config(
        config_dir / "autonomy.yaml"
    )

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
    )


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

    @app.post("/login")
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

    @app.post("/logout")
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
                new_tool_calls = [
                    e for e in prev_pass_events if e.type == EventType.TOOL_CALL
                ]
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
                        if e.id == body.pending_event_id
                        and e.type == EventType.TOOL_CALL_PENDING
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

        yield

        # Tear down sweeper before ctx.shutdown() (cancel cleanly, no pending-task warning).
        if _sweeper_task is not None:
            _sweeper_task.cancel()
            with suppress(asyncio.CancelledError):
                await _sweeper_task
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
