"""Tests for /pipelines* endpoints (ADR-041 D7 / T5).

Covers:
- POST /pipelines: create, validation, owner captured from principal
- GET /pipelines: returns only caller's own definitions
- GET /pipelines/{id}: 404 for missing, 403 for non-owner
- POST /pipelines/{id}/run: 404 for missing, 403 for non-owner, run result
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.api.app import AppContext, _make_test_app
from orchestrator.api.auth.session import create_token
from orchestrator.api.auth.users import create_user, init_auth_schema
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.core.event import RoomId
from orchestrator.core.event_store import EventStore
from orchestrator.llm.types import (
    LLMResponse,
    ModelId,
    ProviderId,
    Usage,
    generate_request_id,
)
from orchestrator.pipeline.store import init_pipeline_schema

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_USER_A = "alice"
_USER_B = "bob"
_PASSWORD = "test-password-xyz"


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        request_id=generate_request_id(),
        content=content,
        tool_calls=[],
        model_id_requested=ModelId("m1"),
        model_id_used=ModelId("m1"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=1, output_tokens=1),
        latency_ms=0,
        finish_reason="stop",
    )


def _mock_router(content: str = "analysis result") -> MagicMock:
    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = [_llm_response(content), _llm_response("summary " + content)]
    return router


@pytest.fixture
def pipeline_db(tmp_path: Path) -> Path:
    return tmp_path / "pipeline_test.db"


@pytest.fixture
def pipeline_ctx(pipeline_db: Path) -> Generator[AppContext, None, None]:
    """AppContext with two users and pipeline schema initialized."""
    writer_conn = sqlite3.connect(str(pipeline_db), check_same_thread=False)
    writer_store = EventStore(writer_conn)
    writer_store.init_schema()
    writer_conn.execute("PRAGMA journal_mode=WAL")
    writer_conn.commit()

    init_auth_schema(writer_conn)
    init_pipeline_schema(writer_conn)

    create_user(writer_conn, _USER_A, _PASSWORD)
    create_user(writer_conn, _USER_B, _PASSWORD)

    reader_conn = sqlite3.connect(str(pipeline_db), check_same_thread=False)
    reader_store = EventStore(reader_conn)

    _reader_local: threading.local = threading.local()
    _reader_conns: list[sqlite3.Connection] = []
    _reader_conns_lock = threading.Lock()

    def _init_reader() -> None:
        conn = sqlite3.connect(str(pipeline_db), check_same_thread=False)
        _reader_local.conn = conn
        _reader_local.store = EventStore(conn)
        with _reader_conns_lock:
            _reader_conns.append(conn)

    writer_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipe-test-writer")
    reader_exec = ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="pipe-test-reader", initializer=_init_reader
    )
    bus = RoomEventBus()

    ctx = AppContext(
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
    yield ctx
    ctx.shutdown()


@pytest.fixture
def pipeline_app(pipeline_ctx: AppContext) -> FastAPI:
    return _make_test_app(pipeline_ctx)


def _client_for(app: FastAPI, ctx: AppContext, user_id: str) -> TestClient:
    raw_token = create_token(ctx.writer_store.conn, user_id)
    headers = {"Authorization": f"Bearer {raw_token}"}
    return TestClient(app, raise_server_exceptions=True, headers=headers)


_VALID_BODY: dict[str, Any] = {
    "sources": [{"kind": "web", "locator": "https://example.com/data"}],
    "analysis_prompts": ["Summarize this content"],
}


# ---------------------------------------------------------------------------
# POST /pipelines
# ---------------------------------------------------------------------------


def test_create_pipeline_returns_201(pipeline_app: FastAPI, pipeline_ctx: AppContext) -> None:
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client:
        resp = client.post("/pipelines", json=_VALID_BODY)
    assert resp.status_code == 201
    data = resp.json()
    assert data["pipeline_id"].startswith("pipe_")
    assert data["owner_user_id"] == _USER_A
    assert data["enabled"] is True
    assert data["analysis_prompts"] == ["Summarize this content"]


def test_create_pipeline_owner_from_principal(
    pipeline_app: FastAPI, pipeline_ctx: AppContext
) -> None:
    """owner_user_id is derived from the principal, not from the request body."""
    with _client_for(pipeline_app, pipeline_ctx, _USER_B) as client:
        resp = client.post("/pipelines", json=_VALID_BODY)
    assert resp.status_code == 201
    assert resp.json()["owner_user_id"] == _USER_B


def test_create_pipeline_unauthenticated(pipeline_app: FastAPI) -> None:
    with TestClient(pipeline_app, raise_server_exceptions=True) as client:
        resp = client.post("/pipelines", json=_VALID_BODY)
    assert resp.status_code in (401, 403)


def test_create_pipeline_invalid_source_kind(
    pipeline_app: FastAPI, pipeline_ctx: AppContext
) -> None:
    body = {
        "sources": [{"kind": "ftp", "locator": "ftp://example.com"}],
        "analysis_prompts": ["Analyze"],
    }
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client:
        resp = client.post("/pipelines", json=body)
    assert resp.status_code == 422


def test_create_pipeline_empty_prompts_rejected(
    pipeline_app: FastAPI, pipeline_ctx: AppContext
) -> None:
    body = {
        "sources": [{"kind": "web", "locator": "https://example.com"}],
        "analysis_prompts": [],
    }
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client:
        resp = client.post("/pipelines", json=body)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /pipelines
# ---------------------------------------------------------------------------


def test_list_pipelines_returns_own_only(pipeline_app: FastAPI, pipeline_ctx: AppContext) -> None:
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client:
        client.post("/pipelines", json=_VALID_BODY)
        client.post("/pipelines", json=_VALID_BODY)
        resp = client.get("/pipelines")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(d["owner_user_id"] == _USER_A for d in data)

    with _client_for(pipeline_app, pipeline_ctx, _USER_B) as client:
        resp_b = client.get("/pipelines")
    assert resp_b.status_code == 200
    assert resp_b.json() == []  # bob has no pipelines


def test_list_pipelines_unauthenticated(pipeline_app: FastAPI) -> None:
    with TestClient(pipeline_app, raise_server_exceptions=True) as client:
        resp = client.get("/pipelines")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /pipelines/{id}
# ---------------------------------------------------------------------------


def test_get_pipeline_owner_can_read(pipeline_app: FastAPI, pipeline_ctx: AppContext) -> None:
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client:
        create_resp = client.post("/pipelines", json=_VALID_BODY)
        pipeline_id = create_resp.json()["pipeline_id"]
        get_resp = client.get(f"/pipelines/{pipeline_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["pipeline_id"] == pipeline_id


def test_get_pipeline_non_owner_gets_403(pipeline_app: FastAPI, pipeline_ctx: AppContext) -> None:
    """Non-owner principal gets 403 (R0-A F3 — owner-private access control)."""
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client_a:
        create_resp = client_a.post("/pipelines", json=_VALID_BODY)
    pipeline_id = create_resp.json()["pipeline_id"]

    with _client_for(pipeline_app, pipeline_ctx, _USER_B) as client_b:
        resp = client_b.get(f"/pipelines/{pipeline_id}")
    assert resp.status_code == 403


def test_get_pipeline_not_found_returns_404(
    pipeline_app: FastAPI, pipeline_ctx: AppContext
) -> None:
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client:
        resp = client.get("/pipelines/pipe_doesnotexist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /pipelines/{id}/run
# ---------------------------------------------------------------------------


def test_run_pipeline_non_owner_gets_403(pipeline_app: FastAPI, pipeline_ctx: AppContext) -> None:
    """Non-owner gets 403 on run endpoint (R0-A F3)."""
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client_a:
        create_resp = client_a.post("/pipelines", json=_VALID_BODY)
    pipeline_id = create_resp.json()["pipeline_id"]

    with _client_for(pipeline_app, pipeline_ctx, _USER_B) as client_b:
        resp = client_b.post(f"/pipelines/{pipeline_id}/run")
    assert resp.status_code == 403


def test_run_pipeline_not_found_returns_404(
    pipeline_app: FastAPI, pipeline_ctx: AppContext
) -> None:
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client:
        resp = client.post("/pipelines/pipe_doesnotexist/run")
    assert resp.status_code == 404


def test_run_pipeline_returns_run_result(
    pipeline_app: FastAPI, pipeline_ctx: AppContext, tmp_path: Path
) -> None:
    """POST /pipelines/{id}/run runs the pipeline and returns run result."""
    # The mock router returns canned responses; web source will fail (no real network)
    # but the runner records the failure and continues (fail-closed isolation).
    # The run itself still returns 200 with succeeded=True (partial result is fine).
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client:
        create_resp = client.post("/pipelines", json=_VALID_BODY)
        assert create_resp.status_code == 201
        pipeline_id = create_resp.json()["pipeline_id"]

        run_resp = client.post(f"/pipelines/{pipeline_id}/run")

    assert run_resp.status_code == 200
    data = run_resp.json()
    assert "run_id" in data
    assert "room_id" in data
    assert data["pipeline_id"] == pipeline_id
    assert data["run_id"].startswith("prun_")
    assert data["room_id"].startswith("room_")


def test_run_pipeline_unauthenticated(pipeline_app: FastAPI, pipeline_ctx: AppContext) -> None:
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client_a:
        create_resp = client_a.post("/pipelines", json=_VALID_BODY)
    pipeline_id = create_resp.json()["pipeline_id"]

    with TestClient(pipeline_app, raise_server_exceptions=True) as unauth:
        resp = unauth.post(f"/pipelines/{pipeline_id}/run")
    assert resp.status_code in (401, 403)


def test_run_pipeline_run_id_matches_anchor_event(
    pipeline_app: FastAPI, pipeline_ctx: AppContext
) -> None:
    """N1: run_id in API response equals run_id embedded in the room run-anchor event."""
    with _client_for(pipeline_app, pipeline_ctx, _USER_A) as client:
        create_resp = client.post("/pipelines", json=_VALID_BODY)
        assert create_resp.status_code == 201
        pipeline_id = create_resp.json()["pipeline_id"]

        run_resp = client.post(f"/pipelines/{pipeline_id}/run")

    assert run_resp.status_code == 200
    data = run_resp.json()
    run_id: str = data["run_id"]
    room_id: str = data["room_id"]

    events = pipeline_ctx.writer_store.get_room_events(RoomId(room_id))
    assert events, "pipeline run room has no events"
    anchor = events[0]  # run anchor is always the first event
    assert run_id in anchor.content, (
        f"run_id {run_id!r} not found in anchor event content {anchor.content!r}"
    )
