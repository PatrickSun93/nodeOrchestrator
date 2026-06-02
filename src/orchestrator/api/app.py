"""FastAPI application factory and route handlers (ADR-025 D1/D2).

P3.2-1: AppContext type + endpoint declarations (stub handlers for OpenAPI).
P3.2-2: create_app factory + read handler implementations.
P3.2-3: WS live stream + RoomEventBus integration + executor wiring.
P3.2-4: POST /intent write path + forge-prevention + llm_adapter.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel, ConfigDict

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.agents.schema import Agent
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.api.wire import Event, IntentRequest, IntentResponse, Room, Snapshot
from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import RoomType
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


def _register_routes(app: FastAPI, ctx: AppContext) -> None:
    """Register all API routes on the app with captured context.

    P3.2-1: stub handlers for contract / OpenAPI generation.
    Implementations replace the stubs in P3.2-2/3/4.
    ctx is captured by real handlers; unused by stubs.
    """

    @app.post("/rooms", response_model=Room, status_code=201)
    async def _create_room(body: _CreateRoomBody) -> Room:
        raise HTTPException(status_code=501, detail="not implemented")

    @app.get("/rooms/{room_id}", response_model=Room)
    async def _get_room(room_id: str) -> Room:
        raise HTTPException(status_code=501, detail="not implemented")

    @app.get("/rooms/{room_id}/events", response_model=list[Event])
    async def _get_room_events(room_id: str) -> list[Event]:
        raise HTTPException(status_code=501, detail="not implemented")

    @app.get("/rooms/{room_id}/snapshot", response_model=Snapshot)
    async def _get_snapshot(room_id: str) -> Snapshot:
        raise HTTPException(status_code=501, detail="not implemented")

    @app.get("/events/{event_id}/thread", response_model=list[Event])
    async def _get_thread(event_id: str) -> list[Event]:
        raise HTTPException(status_code=501, detail="not implemented")

    @app.post("/rooms/{room_id}/intent", response_model=IntentResponse)
    async def _post_intent(room_id: str, body: IntentRequest) -> IntentResponse:
        raise HTTPException(status_code=501, detail="not implemented")

    @app.websocket("/rooms/{room_id}/stream")
    async def _room_stream(websocket: WebSocket, room_id: str) -> None:
        await websocket.close(code=1011)


def create_app(config_dir: Path, db_path: Path) -> FastAPI:
    """Production factory — full bootstrap + lifespan. Implemented in P3.2-2."""
    raise NotImplementedError(
        "create_app implemented in P3.2-2; use _register_routes(app, ctx) for tests"
    )
