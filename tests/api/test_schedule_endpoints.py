"""Tests for schedule management endpoints (ADR-042 D9 / P5.1b-5).

Covers:
- POST /pipelines/{id}/schedules: owner happy-path, non-owner 403, missing-pipeline 404,
  malformed expr 422, kind=cron → 422 (deferred)
- GET /pipelines/{id}/schedules: owner list, non-owner 403
- DELETE /pipelines/{id}/schedules/{sid}: owner delete, non-owner 403
- PATCH /pipelines/{id}/schedules/{sid}: enable/disable, non-owner 403
- Created interval schedule appears in list_due_schedules once due
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
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
from orchestrator.core.event_store import EventStore
from orchestrator.pipeline.schema import PipelineDefinition
from orchestrator.pipeline.store import (
    create_pipeline,
    init_pipeline_schema,
    list_due_schedules,
)
from orchestrator.sources.schema import Source

_USER_A = "alice_sched"
_USER_B = "bob_sched"
_PW = "pw-sched"


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
        content="result",
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


@pytest.fixture
def sched_ctx(tmp_path: Any) -> Generator[AppContext, None, None]:
    db = tmp_path / "sched_ep.db"
    writer_conn = sqlite3.connect(str(db), check_same_thread=False)
    writer_store = EventStore(writer_conn)
    writer_store.init_schema()
    writer_conn.execute("PRAGMA journal_mode=WAL")
    writer_conn.commit()
    init_auth_schema(writer_conn)
    init_pipeline_schema(writer_conn)
    create_user(writer_conn, _USER_A, _PW)
    create_user(writer_conn, _USER_B, _PW)

    reader_conn = sqlite3.connect(str(db), check_same_thread=False)
    reader_store = EventStore(reader_conn)
    _reader_local: threading.local = threading.local()
    _reader_conns: list[sqlite3.Connection] = []
    lock = threading.Lock()

    def _init_reader() -> None:
        conn = sqlite3.connect(str(db), check_same_thread=False)
        _reader_local.conn = conn
        _reader_local.store = EventStore(conn)
        with lock:
            _reader_conns.append(conn)

    writer_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="se-test-writer")
    reader_exec = ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="se-test-reader", initializer=_init_reader
    )
    ctx = AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=writer_exec,
        reader_executor=reader_exec,
        bus=RoomEventBus(),
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
def sched_app(sched_ctx: AppContext) -> FastAPI:
    return _make_test_app(sched_ctx)


def _client(app: FastAPI, ctx: AppContext, user_id: str) -> TestClient:
    token = create_token(ctx.writer_store.conn, user_id)
    return TestClient(
        app, raise_server_exceptions=True, headers={"Authorization": f"Bearer {token}"}
    )


def _make_pipeline(ctx: AppContext, owner: str = _USER_A) -> str:
    defn = PipelineDefinition(
        sources=[Source(kind="web", locator="https://example.com/")],
        analysis_prompts=["Analyze"],
    )
    rec = create_pipeline(ctx.writer_store.conn, owner_user_id=owner, definition=defn)
    return rec.pipeline_id


_VALID_BODY = {"kind": "interval", "expr": "60"}

# ---------------------------------------------------------------------------
# POST /pipelines/{id}/schedules
# ---------------------------------------------------------------------------


def test_create_schedule_owner_happy_path(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    pipe_id = _make_pipeline(sched_ctx)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        resp = c.post(f"/pipelines/{pipe_id}/schedules", json=_VALID_BODY)
    assert resp.status_code == 201
    data = resp.json()
    assert data["schedule_id"].startswith("psch_")
    assert data["pipeline_id"] == pipe_id
    assert data["owner_user_id"] == _USER_A
    assert data["kind"] == "interval"
    assert data["expr"] == "60"
    assert data["enabled"] is True


def test_create_schedule_non_owner_403(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    pipe_id = _make_pipeline(sched_ctx, owner=_USER_A)
    with _client(sched_app, sched_ctx, _USER_B) as c:
        resp = c.post(f"/pipelines/{pipe_id}/schedules", json=_VALID_BODY)
    assert resp.status_code == 403


def test_create_schedule_missing_pipeline_404(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    with _client(sched_app, sched_ctx, _USER_A) as c:
        resp = c.post("/pipelines/nonexistent/schedules", json=_VALID_BODY)
    assert resp.status_code == 404


def test_create_schedule_malformed_expr_422(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    pipe_id = _make_pipeline(sched_ctx)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        resp = c.post(f"/pipelines/{pipe_id}/schedules", json={"kind": "interval", "expr": "abc"})
    assert resp.status_code == 422


def test_create_schedule_cron_422_deferred(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    """kind=cron is deferred (Y1 routing) — must return 422."""
    pipe_id = _make_pipeline(sched_ctx)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        resp = c.post(
            f"/pipelines/{pipe_id}/schedules",
            json={"kind": "cron", "expr": "*/5 * * * *"},
        )
    assert resp.status_code == 422
    assert "deferred" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /pipelines/{id}/schedules
# ---------------------------------------------------------------------------


def test_list_schedules_owner_happy_path(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    pipe_id = _make_pipeline(sched_ctx)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        c.post(f"/pipelines/{pipe_id}/schedules", json=_VALID_BODY)
        resp = c.get(f"/pipelines/{pipe_id}/schedules")
    assert resp.status_code == 200
    schedules = resp.json()
    assert len(schedules) == 1
    assert schedules[0]["owner_user_id"] == _USER_A


def test_list_schedules_non_owner_403(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    pipe_id = _make_pipeline(sched_ctx, owner=_USER_A)
    with _client(sched_app, sched_ctx, _USER_B) as c:
        resp = c.get(f"/pipelines/{pipe_id}/schedules")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /pipelines/{id}/schedules — missing pipeline → 404 (A5/PVI-4)
# ---------------------------------------------------------------------------


def test_list_schedules_missing_pipeline_404(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    """GET /pipelines/{id}/schedules on missing pipeline returns 404 (verb consistency)."""
    with _client(sched_app, sched_ctx, _USER_A) as c:
        resp = c.get("/pipelines/nonexistent_pipe/schedules")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /pipelines/{id}/schedules/{sid}
# ---------------------------------------------------------------------------


def test_delete_schedule_owner_happy_path(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    pipe_id = _make_pipeline(sched_ctx)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        create_resp = c.post(f"/pipelines/{pipe_id}/schedules", json=_VALID_BODY)
        sid = create_resp.json()["schedule_id"]
        del_resp = c.delete(f"/pipelines/{pipe_id}/schedules/{sid}")
    assert del_resp.status_code == 204


def test_delete_schedule_non_owner_403(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    pipe_id = _make_pipeline(sched_ctx, owner=_USER_A)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        sid = c.post(f"/pipelines/{pipe_id}/schedules", json=_VALID_BODY).json()["schedule_id"]
    with _client(sched_app, sched_ctx, _USER_B) as c:
        resp = c.delete(f"/pipelines/{pipe_id}/schedules/{sid}")
    assert resp.status_code == 403


def test_delete_schedule_cross_pipeline_idor_404(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    """A1/PVI-1: DELETE with S_other's id under P_self's URL must return 404 (IDOR guard)."""
    pipe_self = _make_pipeline(sched_ctx, owner=_USER_A)
    pipe_other = _make_pipeline(sched_ctx, owner=_USER_A)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        sid_other = c.post(f"/pipelines/{pipe_other}/schedules", json=_VALID_BODY).json()[
            "schedule_id"
        ]
        # schedule belongs to pipe_other but URL says pipe_self → 404
        resp = c.delete(f"/pipelines/{pipe_self}/schedules/{sid_other}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /pipelines/{id}/schedules/{sid}
# ---------------------------------------------------------------------------


def test_patch_schedule_disable_enable(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    pipe_id = _make_pipeline(sched_ctx)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        sid = c.post(f"/pipelines/{pipe_id}/schedules", json=_VALID_BODY).json()["schedule_id"]
        disable_resp = c.patch(f"/pipelines/{pipe_id}/schedules/{sid}", json={"enabled": False})
        assert disable_resp.status_code == 200
        assert disable_resp.json()["enabled"] is False

        enable_resp = c.patch(f"/pipelines/{pipe_id}/schedules/{sid}", json={"enabled": True})
        assert enable_resp.status_code == 200
        assert enable_resp.json()["enabled"] is True


def test_patch_schedule_non_owner_403(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    pipe_id = _make_pipeline(sched_ctx, owner=_USER_A)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        sid = c.post(f"/pipelines/{pipe_id}/schedules", json=_VALID_BODY).json()["schedule_id"]
    with _client(sched_app, sched_ctx, _USER_B) as c:
        resp = c.patch(f"/pipelines/{pipe_id}/schedules/{sid}", json={"enabled": False})
    assert resp.status_code == 403


def test_patch_schedule_cross_pipeline_idor_404(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    """A1/PVI-1: PATCH with S_other's id under P_self's URL must return 404 (IDOR guard)."""
    pipe_self = _make_pipeline(sched_ctx, owner=_USER_A)
    pipe_other = _make_pipeline(sched_ctx, owner=_USER_A)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        sid_other = c.post(f"/pipelines/{pipe_other}/schedules", json=_VALID_BODY).json()[
            "schedule_id"
        ]
        # schedule belongs to pipe_other but URL says pipe_self → 404
        resp = c.patch(f"/pipelines/{pipe_self}/schedules/{sid_other}", json={"enabled": False})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Integration: created interval schedule appears in list_due_schedules once due
# ---------------------------------------------------------------------------


def test_created_interval_schedule_appears_in_due_after_time(
    sched_app: FastAPI, sched_ctx: AppContext
) -> None:
    """An interval schedule created now appears in list_due_schedules after interval elapses."""
    from orchestrator.core.event import now_ms

    pipe_id = _make_pipeline(sched_ctx)
    with _client(sched_app, sched_ctx, _USER_A) as c:
        resp = c.post(
            f"/pipelines/{pipe_id}/schedules",
            json={"kind": "interval", "expr": "1"},  # 1-second interval
        )
    assert resp.status_code == 201
    sid = resp.json()["schedule_id"]

    # Not due yet (just created, next_fire is now+1s)
    due_now = list_due_schedules(sched_ctx.writer_store.conn, now_ms())
    assert all(r.schedule_id != sid for r in due_now)

    # Due after 2 seconds
    future_ms = now_ms() + 2_000
    due_future = list_due_schedules(sched_ctx.writer_store.conn, future_ms)
    assert any(r.schedule_id == sid for r in due_future)
