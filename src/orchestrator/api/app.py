"""FastAPI application factory and route handlers (ADR-025 D1/D2).

P3.2-1: AppContext type + endpoint declarations (stub handlers for OpenAPI).
P3.2-2: create_app factory + read handler implementations.
P3.2-3: WS live stream + RoomEventBus integration + executor wiring.
P3.2-4: POST /intent write path + forge-prevention + llm_adapter.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel, ConfigDict

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.agents.loader import load_agents
from orchestrator.agents.schema import Agent
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.api.wire import Event, IntentRequest, IntentResponse, Room, Snapshot
from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.bootstrap import load_and_validate_llm_layer
from orchestrator.core.event import (
    EventId,
    EventNotFoundError,
    RoomId,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room as _CoreRoom
from orchestrator.core.room import RoomType
from orchestrator.derived.snapshot import produce_snapshot
from orchestrator.llm.config_loader import load_tools_config
from orchestrator.llm.types import LLMRequest, LLMResponse
from orchestrator.skills.loader import load_skills
from orchestrator.skills.schema import Skill

PAYLOAD_LIMIT_BYTES = 65_536  # 64 KiB


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

    def shutdown(self) -> None:
        """Tear down executors and DB connections on server stop."""
        self.writer_executor.shutdown(wait=True)
        self.reader_executor.shutdown(wait=True)
        self.writer_store.conn.close()
        self.reader_store.conn.close()


class _CreateRoomBody(BaseModel):
    """Request body for POST /rooms."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: RoomType


class _AppendFailedError(Exception):
    """append() failed — nothing persisted, safe to retry (ADR-025 D5)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _TurnFailedError(Exception):
    """run_turn failed after a successful append — intent IS persisted (ADR-025 D5)."""

    def __init__(self, reason: str, event_id: str) -> None:
        self.reason = reason
        self.event_id = event_id
        super().__init__(reason)


class _NoopLLMRouter:
    """Placeholder until P3.2-4 installs RealLLMRouter via _build_context."""

    def call(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError(
            "_NoopLLMRouter: LLM router not configured. "
            "Pass a real config_dir with providers/models to create_app."
        )


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

    # Reader: check_same_thread=False for concurrent reads on the read executor
    reader_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    reader_store = EventStore(reader_conn)

    writer_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="api-writer")
    reader_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="api-reader")
    bus = RoomEventBus()

    llm_layer = load_and_validate_llm_layer(config_dir)
    agents, regex_registry = load_agents(config_dir / "agents", models=llm_layer.models)
    skills = load_skills(config_dir / "skills")
    tools = load_tools_config(config_dir / "tools.yaml")

    # P3.2-4: RealLLMRouter imported and installed here.
    llm_router: LLMRouterProtocol = _NoopLLMRouter()

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
    )


def _register_routes(app: FastAPI, ctx: AppContext) -> None:
    """Register all API routes on the app with captured context.

    P3.2-2: read handlers (create/GET rooms, events, snapshot, thread).
    P3.2-3: WS live stream.
    P3.2-4: POST /intent write path.
    """

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
            lambda: ctx.reader_store.get_room(RoomId(room_id)),
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"room {room_id!r} not found")
        return result

    @app.get("/rooms/{room_id}/events", response_model=list[Event])
    async def _get_room_events(room_id: str) -> list[Event]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            ctx.reader_executor,
            lambda: ctx.reader_store.get_room_events(RoomId(room_id)),
        )

    @app.get("/rooms/{room_id}/snapshot", response_model=Snapshot)
    async def _get_snapshot(room_id: str) -> Snapshot:
        loop = asyncio.get_running_loop()
        room, events = await asyncio.gather(
            loop.run_in_executor(
                ctx.reader_executor,
                lambda: ctx.reader_store.get_room(RoomId(room_id)),
            ),
            loop.run_in_executor(
                ctx.reader_executor,
                lambda: ctx.reader_store.get_room_events(RoomId(room_id)),
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
                lambda: ctx.reader_store.get_thread(EventId(event_id)),
            )
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"event {event_id!r} not found") from exc

    @app.post("/rooms/{room_id}/intent", response_model=IntentResponse)
    async def _post_intent(room_id: str, body: IntentRequest) -> IntentResponse:
        # P3.2-4: full forge-prevention + run_turn + publish implementation.
        raise HTTPException(status_code=501, detail="not implemented")

    @app.websocket("/rooms/{room_id}/stream")
    async def _room_stream(websocket: WebSocket, room_id: str) -> None:
        # P3.2-3: subscribe-then-replay+dedup WS handler.
        await websocket.close(code=1011)


def create_app(config_dir: Path, db_path: Path) -> FastAPI:
    """Production factory — builds context, registers routes, manages lifecycle.

    create_app(config_dir, db_path) is the single entry point for all
    production usage. Tests use _make_test_app(ctx) to inject a pre-built
    AppContext (bypassing the full bootstrap).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ctx = _build_context(config_dir, db_path)
        _register_routes(app, ctx)
        yield
        ctx.shutdown()

    return FastAPI(
        title="Orchestrator API",
        version="0.1.0",
        description="HTTP/WS API over the event store and room runtime (ADR-025)",
        lifespan=lifespan,
    )


def _make_test_app(ctx: AppContext) -> FastAPI:
    """Test helper: creates an app with pre-built context (no lifespan bootstrap)."""
    app = FastAPI(title="Orchestrator API [test]", version="0.1.0")
    _register_routes(app, ctx)
    return app
