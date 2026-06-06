"""P3.4-C2-3 e2e tests: full runtime turn with the executor wired.

Tests the complete _write_and_turn path: POST /intent → run_turn →
execute_pending_tool_calls → TOOL_RESULT/OBSERVATION in room events.

Three constitutional demonstrations (per plan §2 C2-3):
  e2e_local: get_current_time (local AUTO) → TOOL_RESULT (no interpret)
  e2e_mcp:   mcp__test__read (MCP AUTO, mocked session) → TOOL_RESULT + OBSERVATION
  e2e_hard:  mcp__test__write (HARD_CONFIRM) → no TOOL_CALL, no TOOL_RESULT

Also:
  bootstrap: AppContext.mcp_sessions defaults to {} when not explicitly provided.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from mcp.types import CallToolResult, TextContent, Tool

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.api.app import AppContext, _make_test_app
from orchestrator.api.auth.session import create_token
from orchestrator.api.auth.users import create_user, init_auth_schema
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.core.event import (
    Event,
    EventType,
    ToolCallPendingMeta,
    build_author,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import (
    AgentAutonomyThresholds,
    AgentLLMConfig,
    LLMRequest,
    LLMResponse,
    ModelId,
    ProviderId,
    RequestId,
    ToolCall,
    Usage,
)
from orchestrator.mcp.client import MCPSession
from orchestrator.mcp.transport import MCPTransport
from orchestrator.tools.local import build_local_tool_registry
from orchestrator.tools.mutation_tools import build_mutation_tool_registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_MODEL = ModelId("mock-model")
_TEST_USER = "e2etest"
_TEST_PW = "e2e-test-pw"


def _make_authed_client(app: Any, ctx: AppContext) -> TestClient:
    """Build a TestClient with bearer-token auth for _TEST_USER."""
    raw_token = create_token(ctx.writer_store.conn, _TEST_USER)
    return TestClient(app, headers={"Authorization": f"Bearer {raw_token}"})
_MOCK_PROVIDER = ProviderId("mock-provider")


def _llm_ok(
    request_id: str,
    content: str = "",
    tool_calls: list[ToolCall] | None = None,
) -> LLMResponse:
    return LLMResponse(
        request_id=RequestId(request_id),
        content=content,
        tool_calls=tool_calls or [],
        model_id_requested=_MOCK_MODEL,
        model_id_used=_MOCK_MODEL,
        provider_id_used=_MOCK_PROVIDER,
        usage=Usage(input_tokens=5, output_tokens=10),
        latency_ms=0,
        finish_reason="stop",
    )


def _make_tool_calling_router(tool_name: str, call_id: str = "tc_e2e") -> LLMRouterProtocol:
    """Mock router: AGENT_RESPONSE returns tool call; TOOL_OUTPUT_INTERPRET returns text."""
    mock = MagicMock(spec=LLMRouterProtocol)

    def _call(req: LLMRequest) -> LLMResponse:
        if req.purpose == LLMPurpose.AGENT_RESPONSE:
            return _llm_ok(
                str(req.request_id),
                tool_calls=[ToolCall(id=call_id, name=tool_name, arguments={})],
            )
        return _llm_ok(str(req.request_id), content="the tool returned a result")

    mock.call.side_effect = _call
    return mock


def _make_agent(agent_id: str = "tester") -> Any:
    """Build a minimal Agent that speaks on USER_INPUT."""
    from orchestrator.agents.schema import Agent, AgentAppliesTo, EventTypeTrigger

    return Agent(
        id=agent_id,
        role="test role",
        persona="test persona",
        speaking_triggers=[EventTypeTrigger(event_type=EventType.USER_INPUT)],
        llm_config=AgentLLMConfig(
            default_model=_MOCK_MODEL,
            autonomy_thresholds=AgentAutonomyThresholds(
                threshold_auto=7,
                threshold_confirm=3,
                user_intent_modifier=0,
            ),
        ),
        applies_to=AgentAppliesTo(room_types=["*"], room_states=["*"]),
    )


def _make_ctx(
    *,
    db_path: Path,
    tools: dict[str, ToolMeta],
    llm_router: LLMRouterProtocol,
    mcp_sessions: dict[str, MCPSession] | None = None,
    sandbox_root: Path | None = None,
) -> AppContext:
    """Build a test AppContext with executor fields wired."""
    writer_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    writer_store = EventStore(writer_conn)
    writer_store.init_schema()
    writer_conn.execute("PRAGMA journal_mode=WAL")
    writer_conn.commit()
    init_auth_schema(writer_conn)
    create_user(writer_conn, _TEST_USER, _TEST_PW)

    reader_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    reader_store = EventStore(reader_conn)

    writer_exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="e2e-writer")
    reader_exec = ThreadPoolExecutor(max_workers=2, thread_name_prefix="e2e-reader")

    root = sandbox_root or Path(".")
    local_tools = {
        **build_local_tool_registry(root),
        **build_mutation_tool_registry(root),
    }

    return AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=writer_exec,
        reader_executor=reader_exec,
        bus=RoomEventBus(),
        available_agents={"tester": _make_agent()},
        available_skills={},
        regex_registry={},
        tools=tools,
        llm_router=llm_router,
        mcp_sessions=mcp_sessions or {},
        local_tools=local_tools,
        sandbox_root=root,
    )


# ---------------------------------------------------------------------------
# e2e: local AUTO tool → TOOL_RESULT (no interpret)
# ---------------------------------------------------------------------------


def test_e2e_local_auto_tool_appends_tool_result(tmp_path: Path) -> None:
    """Full turn: agent calls get_current_time (local AUTO) → TOOL_RESULT in events."""
    db = tmp_path / "e2e.db"
    tools = {"get_current_time": ToolMeta(reversibility=10)}
    router = _make_tool_calling_router("get_current_time")

    ctx = _make_ctx(db_path=db, tools=tools, llm_router=router, sandbox_root=tmp_path)
    app = _make_test_app(ctx)

    with _make_authed_client(app, ctx) as client:
        room_id = client.post("/rooms", json={"type": "free_chat"}).json()["id"]
        resp = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "what time is it?"},
        )
        assert resp.status_code == 200
        events = client.get(f"/rooms/{room_id}/events").json()

    event_types = [e["type"] for e in events]
    assert "tool_call" in event_types, f"TOOL_CALL missing: {event_types}"
    assert "tool_result" in event_types, f"TOOL_RESULT missing: {event_types}"
    # Local tool is trusted — NOT interpreted (no OBSERVATION)
    assert "observation" not in event_types, f"unexpected OBSERVATION: {event_types}"

    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["metadata"]["success"] is True

    ctx.shutdown()


# ---------------------------------------------------------------------------
# e2e: MCP AUTO tool → TOOL_RESULT + OBSERVATION (interpret)
# ---------------------------------------------------------------------------


def test_e2e_mcp_auto_tool_appends_tool_result_and_observation(tmp_path: Path) -> None:
    """Full turn: agent calls MCP AUTO tool (mocked) → TOOL_RESULT + OBSERVATION."""
    db = tmp_path / "e2e_mcp.db"

    mock_transport = MagicMock(spec=MCPTransport)
    mock_transport.call_tool.return_value = CallToolResult(
        content=[TextContent(type="text", text="mcp read result")],
        isError=False,
    )
    mcp_session = MCPSession(
        server_name="test",
        tools=[Tool(name="read", inputSchema={"type": "object"})],
        transport=mock_transport,
    )

    tools = {"mcp__test__read": ToolMeta(reversibility=10)}
    router = _make_tool_calling_router("mcp__test__read", call_id="tc_mcp")

    ctx = _make_ctx(
        db_path=db,
        tools=tools,
        llm_router=router,
        mcp_sessions={"test": mcp_session},
        sandbox_root=tmp_path,
    )
    app = _make_test_app(ctx)

    with _make_authed_client(app, ctx) as client:
        room_id = client.post("/rooms", json={"type": "free_chat"}).json()["id"]
        resp = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "read some file"},
        )
        assert resp.status_code == 200
        events = client.get(f"/rooms/{room_id}/events").json()

    event_types = [e["type"] for e in events]
    assert "tool_call" in event_types, f"TOOL_CALL missing: {event_types}"
    assert "tool_result" in event_types, f"TOOL_RESULT missing: {event_types}"
    assert "observation" in event_types, f"OBSERVATION missing (MCP interpret): {event_types}"

    ctx.shutdown()


# ---------------------------------------------------------------------------
# e2e: HARD MCP tool → no TOOL_CALL, no TOOL_RESULT (gated-not-executed)
# ---------------------------------------------------------------------------


def test_e2e_hard_mcp_tool_not_executed(tmp_path: Path) -> None:
    """Full turn: agent calls HARD_CONFIRM tool → no TOOL_CALL, no TOOL_RESULT."""
    db = tmp_path / "e2e_hard.db"

    tools = {"mcp__test__write": ToolMeta(reversibility=2)}
    router = _make_tool_calling_router("mcp__test__write", call_id="tc_hard")

    ctx = _make_ctx(db_path=db, tools=tools, llm_router=router, sandbox_root=tmp_path)
    app = _make_test_app(ctx)

    with _make_authed_client(app, ctx) as client:
        room_id = client.post("/rooms", json={"type": "free_chat"}).json()["id"]
        resp = client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "write a file"},
        )
        assert resp.status_code == 200
        events = client.get(f"/rooms/{room_id}/events").json()

    event_types = [e["type"] for e in events]
    # HARD_CONFIRM: no TOOL_CALL appended by gate → executor has nothing to execute
    assert "tool_call" not in event_types, f"unexpected TOOL_CALL: {event_types}"
    assert "tool_result" not in event_types, f"unexpected TOOL_RESULT: {event_types}"
    # gate records its decision
    assert "autonomy_decision" in event_types, f"autonomy_decision missing: {event_types}"

    ctx.shutdown()


# ---------------------------------------------------------------------------
# bootstrap: AppContext.mcp_sessions defaults to empty dict
# ---------------------------------------------------------------------------


def test_app_context_mcp_sessions_default_empty() -> None:
    """AppContext.mcp_sessions defaults to {} when not explicitly provided."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = EventStore(conn)
    store.init_schema()

    class _Noop:
        def call(self, req: LLMRequest) -> LLMResponse:
            raise RuntimeError("not called")

    ctx = AppContext(
        writer_store=store,
        reader_store=store,
        writer_executor=ThreadPoolExecutor(max_workers=1),
        reader_executor=ThreadPoolExecutor(max_workers=1),
        bus=RoomEventBus(),
        available_agents={},
        available_skills={},
        regex_registry={},
        tools={},
        llm_router=_Noop(),
    )
    assert ctx.mcp_sessions == {}
    assert ctx.local_tools == {}
    ctx.shutdown()


# ---------------------------------------------------------------------------
# B5-4: apply_edit confirmed TOOL_CALL actuates (no longer not_implemented)
# ---------------------------------------------------------------------------


def test_e2e_apply_edit_confirm_actuates(tmp_path: Path) -> None:
    """Confirmed apply_edit TOOL_CALL actually writes the file (no longer not_implemented).

    Integration: TOOL_CALL_PENDING → POST /confirm approve → TOOL_RESULT contains
    'wrote N bytes'; file exists on disk.  Verifies B5-4 wiring is complete.
    """
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    target_rel = "output/result.txt"
    content_to_write = "hello from apply_edit"

    # Minimal AppContext with mutation_tools wired.
    db = tmp_path / "e2e_apply.db"
    writer_conn = sqlite3.connect(str(db), check_same_thread=False)
    writer_store = EventStore(writer_conn)
    writer_store.init_schema()
    writer_conn.execute("PRAGMA journal_mode=WAL")
    writer_conn.commit()
    init_auth_schema(writer_conn)
    create_user(writer_conn, _TEST_USER, _TEST_PW)
    reader_conn = sqlite3.connect(str(db), check_same_thread=False)
    reader_store = EventStore(reader_conn)

    local_tools_map = {
        **build_local_tool_registry(sandbox),
        **build_mutation_tool_registry(sandbox),
    }

    class _NullRouter:
        def call(self, req: object) -> object:
            raise RuntimeError("not expected")

    ctx = AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="b54-writer"),
        reader_executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="b54-reader"),
        bus=RoomEventBus(),
        available_agents={},
        available_skills={},
        regex_registry={},
        tools={"apply_edit": ToolMeta(reversibility=2)},
        llm_router=_NullRouter(),  # type: ignore[arg-type]
        local_tools=local_tools_map,
        sandbox_root=sandbox,
    )
    app = _make_test_app(ctx)

    rid = generate_room_id()
    writer_store.append_room(Room(id=rid, type=RoomType.FREE_CHAT, state="open"))

    # Append TOOL_CALL_PENDING for apply_edit.
    pending = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_CALL_PENDING,
        author=build_author("operator"),
        timestamp=now_ms(),
        content="",
        metadata=ToolCallPendingMeta(
            tool_name="apply_edit",
            call_id="call_apply_b54",
            params={"path": target_rel, "content": content_to_write},
            tier="hard_confirm",
            initiating_agent="operator",
        ).model_dump(),
    )
    writer_store.append(pending)

    with _make_authed_client(app, ctx) as client:
        r = client.post(
            f"/rooms/{rid}/confirm",
            json={"pending_event_id": pending.id, "decision": "approve"},
        )

    ctx.shutdown()

    assert r.status_code == 200, f"confirm failed: {r.json()}"
    turn_events = r.json().get("turn_events", [])
    event_types = [e["type"] for e in turn_events]
    assert "tool_result" in event_types, f"TOOL_RESULT missing after confirm: {event_types}"

    # Verify the result content shows successful write (not "not_implemented").
    result_events = [e for e in turn_events if e["type"] == "tool_result"]
    result_content = result_events[0]["content"]
    assert "wrote" in result_content, (
        f"apply_edit result should say 'wrote N bytes', got: {result_content!r}"
    )
    assert "not_implemented" not in result_content.lower(), (
        f"apply_edit still not_implemented: {result_content!r}"
    )

    # File must exist on disk.
    assert (sandbox / target_rel).exists(), "apply_edit did not create the file on disk"
    assert (sandbox / target_rel).read_text() == content_to_write


def test_e2e_send_email_unconfigured_fail_closed(tmp_path: Path) -> None:
    """send_email without email.yaml → fail-closed (not a crash/500).

    email.yaml absence → the registry builds with fail-closed send_email;
    calling it raises LocalToolError "not configured", not a server error.
    """
    from orchestrator.tools.local import LocalToolError
    from orchestrator.tools.network_tools import build_network_tool_registry as _build_net

    # No email_config_path → unconfigured provider.
    registry = _build_net()
    with pytest.raises(LocalToolError, match="not configured"):
        registry["send_email"]({"to": "a@example.com", "subject": "s", "body": "b"})
