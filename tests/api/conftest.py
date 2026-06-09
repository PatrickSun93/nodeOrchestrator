"""Shared fixtures for api tests."""

from __future__ import annotations

import sqlite3
import threading
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
from orchestrator.api.auth.session import create_token
from orchestrator.api.auth.users import create_user, init_auth_schema
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
from orchestrator.pipeline.store import init_pipeline_schema

# ---------------------------------------------------------------------------
# Test auth credentials
# ---------------------------------------------------------------------------

TEST_USER_ID = "testuser"
TEST_PASSWORD = "test-password-123"

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
    """AppContext with two real SQLite connections on a temp file DB.

    Auth schema (users/sessions/user_tokens) is initialized so the auth
    middleware can run. A TEST_USER_ID test account is pre-created.
    """
    writer_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    writer_store = EventStore(writer_conn)
    writer_store.init_schema()
    writer_conn.execute("PRAGMA journal_mode=WAL")
    writer_conn.commit()

    # Initialize auth tables on writer (co-located in same DB, ADR-039 D2)
    init_auth_schema(writer_conn)

    # Initialize pipeline tables on writer (co-located in same DB, ADR-041 D8)
    init_pipeline_schema(writer_conn)

    # Create a test user for authenticated fixtures
    create_user(writer_conn, TEST_USER_ID, TEST_PASSWORD)

    reader_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    reader_store = EventStore(reader_conn)

    # Per-thread reader connections mirror production (RW7 fix).
    # Each worker thread gets its own SQLite connection via the initializer;
    # WAL mode lets all of them read concurrently without contention.
    _reader_local: threading.local = threading.local()
    _reader_conns: list[sqlite3.Connection] = []
    _reader_conns_lock = threading.Lock()

    def _init_reader_worker() -> None:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _reader_local.conn = conn
        _reader_local.store = EventStore(conn)
        with _reader_conns_lock:
            _reader_conns.append(conn)

    writer_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-writer")
    reader_exec = ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="test-reader",
        initializer=_init_reader_worker,
    )
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
        reader_local=_reader_local,
        reader_conns=_reader_conns,
    )
    yield context
    context.shutdown()


@pytest.fixture
def app(ctx: AppContext) -> FastAPI:
    return _make_test_app(ctx)


@pytest.fixture
def client(app: FastAPI, ctx: AppContext) -> Generator[TestClient, None, None]:
    """Authenticated TestClient — uses a bearer token for TEST_USER_ID.

    Bearer token auth avoids the Secure-cookie/HTTP issue in TestClient.
    All protected routes are accessible. Tests that want to exercise the
    401 path should use `unauth_client` instead.
    """
    raw_token = create_token(ctx.writer_store.conn, TEST_USER_ID)
    headers = {"Authorization": f"Bearer {raw_token}"}
    with TestClient(app, raise_server_exceptions=True, headers=headers) as tc:
        yield tc


@pytest.fixture
def unauth_client(app: FastAPI) -> Generator[TestClient, None, None]:
    """Unauthenticated TestClient — for testing 401 behaviour."""
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc


# ---------------------------------------------------------------------------
# Auth helpers — for tests that create TestClient inline
# ---------------------------------------------------------------------------


def make_auth_headers(ctx: AppContext) -> dict[str, str]:
    """Return Authorization headers for TEST_USER_ID (bearer token).

    Use in inline TestClient creations:
        with TestClient(app, headers=make_auth_headers(ctx)) as client:
    Requires the ctx fixture (which creates the TEST_USER_ID account).
    """
    raw_token = create_token(ctx.writer_store.conn, TEST_USER_ID)
    return {"Authorization": f"Bearer {raw_token}"}


# ---------------------------------------------------------------------------
# Turn result helpers
# ---------------------------------------------------------------------------


def empty_turn() -> TurnResult:
    return TurnResult(utterances=[], total_asked=0)
