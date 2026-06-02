"""Shared fixtures for api tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.agents.schema import TurnResult
from orchestrator.api.app import AppContext, _make_test_app
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.core.event import generate_event_id
from orchestrator.core.event_store import EventStore
from orchestrator.llm.types import (
    LLMResponse,
    ModelId,
    ProviderId,
    RequestId,
    Usage,
)

# ---------------------------------------------------------------------------
# Mock LLM router
# ---------------------------------------------------------------------------


def _mock_router(content: str = "agent reply") -> MagicMock:
    """Build a MagicMock satisfying LLMRouterProtocol."""
    router = MagicMock(spec=LLMRouterProtocol)
    response = LLMResponse(
        request_id=RequestId(generate_event_id()),
        content=content,
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


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def ctx(db_path: Path) -> Generator[AppContext, None, None]:
    """AppContext with two real SQLite connections on a temp file DB."""
    writer_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    writer_store = EventStore(writer_conn)
    writer_store.init_schema()
    writer_conn.execute("PRAGMA journal_mode=WAL")
    writer_conn.commit()

    reader_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    reader_store = EventStore(reader_conn)

    writer_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-writer")
    reader_exec = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-reader")
    bus = RoomEventBus()

    context = AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=writer_exec,
        reader_executor=reader_exec,
        bus=bus,
        available_agents={},
        available_skills={},
        regex_registry={},
        tools={},
        llm_router=_mock_router(),
    )
    yield context
    context.shutdown()


@pytest.fixture
def app(ctx: AppContext) -> FastAPI:
    return _make_test_app(ctx)


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# Turn result helpers
# ---------------------------------------------------------------------------


def empty_turn() -> TurnResult:
    return TurnResult(utterances=[], total_asked=0)
