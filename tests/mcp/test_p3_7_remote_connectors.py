"""P3.7-remote-3: remote demo connector + e2e pipeline tests (ADR-032 D4).

Demonstrates and tests:
  - read-tier AUTO loop end-to-end: streamable_http query_items rev=10 →
    AUTO_EXECUTE → TOOL_CALL appended → execute → TOOL_RESULT appended.
  - fail-closed paths: non-allowlisted-URL (http://) → ConfigError;
    unclassified tool → refused; unreachable → TOOL_FAILED;
    auth-fail → TOOL_FAILED.

The pipeline test uses a mocked MCPTransport (no real https server in CI).
Real endpoint demo: set REMOTE_DEMO_API_KEY env var and point config/mcp_servers.yaml
remote_demo url at a live streamable-http MCP server.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from mcp.types import CallToolResult, TextContent, Tool

from orchestrator.agents.tool_dispatch import process_tool_calls
from orchestrator.autonomy.scoring import AutonomyTier, ThresholdConfig
from orchestrator.core.event import (
    Event,
    EventType,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.exceptions import ConfigError
from orchestrator.llm.types import ToolCall
from orchestrator.mcp.adapter import build_tool_registry
from orchestrator.mcp.client import MCPSession
from orchestrator.mcp.config import (
    MCPServerConfig,
    MCPTimeouts,
    MCPToolConfig,
    load_mcp_servers_config,
)
from orchestrator.mcp.execution import execute_mcp_tool_call
from orchestrator.mcp.transport import MCPConnectionError, MCPTimeoutError, MCPTransport

_THRESHOLDS = ThresholdConfig(threshold_auto=7, threshold_confirm=3, user_intent_modifier=0)
# query_items rev=10 >= auto=7 → AUTO_EXECUTE
# unregistered tool → HARD_CONFIRM at gate (not AUTO_EXECUTE)

_REAL_CONFIG = Path(__file__).resolve().parent.parent.parent / "config" / "mcp_servers.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:")
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room(store: EventStore) -> Any:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


def _make_trigger_event(room_id: Any) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.USER_INPUT,
        author="user",
        timestamp=now_ms(),
        content="query the remote items",
    )


def _remote_cfg(
    url: str = "https://api.example.com/mcp",
    api_key_env: str | None = "REMOTE_DEMO_API_KEY",
) -> MCPServerConfig:
    return MCPServerConfig(
        transport="streamable_http",
        url=url,
        api_key_env=api_key_env,
        tools={"query_items": MCPToolConfig(reversibility=10)},
    )


def _make_tool(name: str) -> Tool:
    return Tool(name=name, inputSchema={"type": "object", "properties": {}})


# ---------------------------------------------------------------------------
# config/mcp_servers.yaml: remote_demo entry loads correctly
# ---------------------------------------------------------------------------


def test_mcp_servers_yaml_remote_demo_entry_loads() -> None:
    """config/mcp_servers.yaml remote_demo entry is valid streamable_http config."""
    if not _REAL_CONFIG.exists():
        pytest.skip("config/mcp_servers.yaml not present")

    cfg = load_mcp_servers_config(_REAL_CONFIG)
    assert "remote_demo" in cfg.servers, (
        "remote_demo entry missing from config/mcp_servers.yaml (P3.7-remote-3)"
    )
    rd = cfg.servers["remote_demo"]
    assert rd.transport == "streamable_http"
    assert rd.url is not None and rd.url.startswith("https://")
    assert rd.tools.get("query_items") is not None
    assert rd.tools["query_items"].reversibility == 10


# ---------------------------------------------------------------------------
# End-to-end: read-tier AUTO loop (mocked transport for CI hermeticity)
# ---------------------------------------------------------------------------


def test_remote_read_tier_auto_loop_e2e() -> None:
    """query_items rev=10 → AUTO_EXECUTE → TOOL_CALL → mocked execute → TOOL_RESULT.

    Demonstrates the full gate→execute pipeline for a streamable_http MCP tool.
    Transport mocked for CI hermeticity (no real HTTPS server needed in CI).
    """
    store = _make_store()
    room_id = _make_room(store)
    user_event = _make_trigger_event(room_id)
    store.append(user_event)

    cfg = _remote_cfg()
    registry = build_tool_registry("remote_demo", cfg, [_make_tool("query_items")])

    # Step 1: Gate — should AUTO_EXECUTE (query_items rev=10 >= auto=7)
    result = process_tool_calls(
        [ToolCall(id="tc_remote_1", name="mcp__remote_demo__query_items", arguments={})],
        agent_id="test",
        room_id=room_id,
        current_event=user_event,
        event_store=store,
        tools=registry,
        thresholds=_THRESHOLDS,
    )
    assert result.decisions[0].tier == AutonomyTier.AUTO_EXECUTE
    assert result.decisions[0].tool_call_event_appended is True

    events = store.get_room_events(room_id)
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 1

    # Step 2: Execute (mocked transport — hermeticity for CI)
    mock_transport = MagicMock(spec=MCPTransport)
    mock_transport.call_tool.return_value = CallToolResult(
        content=[TextContent(type="text", text="remote items: [item_A, item_B]")],
        isError=False,
    )
    session = MCPSession(
        server_name="remote_demo",
        tools=[_make_tool("query_items")],
        transport=mock_transport,
    )

    execute_mcp_tool_call(
        tool_call_event=tool_call_events[0],
        session=session,
        event_store=store,
        room_id=room_id,
        agent_id="test",
    )

    events = store.get_room_events(room_id)
    tool_result_events = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(tool_result_events) == 1
    assert "item_A" in tool_result_events[0].content
    assert tool_result_events[0].metadata["success"] is True


# ---------------------------------------------------------------------------
# fail-closed: non-allowlisted URL (http://) → ConfigError
# ---------------------------------------------------------------------------


def test_remote_non_https_url_config_error(tmp_path: Path) -> None:
    """http:// URL in streamable_http config → ConfigError (TLS mandatory, HR#6)."""
    cfg_path = tmp_path / "mcp.yaml"
    cfg_path.write_text(
        """
servers:
  bad_remote:
    transport: streamable_http
    url: "http://api.example.com/mcp"
    tools: {}
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_mcp_servers_config(cfg_path)


# ---------------------------------------------------------------------------
# fail-closed: unclassified tool → not AUTO_EXECUTE
# ---------------------------------------------------------------------------


def test_remote_unclassified_tool_not_auto_executed() -> None:
    """streamable_http tool not in config allowlist → not AUTO_EXECUTE (discovery != permission)."""
    store = _make_store()
    room_id = _make_room(store)
    user_event = _make_trigger_event(room_id)
    store.append(user_event)

    cfg = _remote_cfg()
    # Register only query_items; delete_items is NOT in the allowlist
    registry = build_tool_registry(
        "remote_demo", cfg, [_make_tool("query_items"), _make_tool("delete_items")]
    )
    # delete_items is NOT in registry (discovery != permission, HR#3)

    result = process_tool_calls(
        [ToolCall(id="tc_unclassified", name="mcp__remote_demo__delete_items", arguments={})],
        agent_id="test",
        room_id=room_id,
        current_event=user_event,
        event_store=store,
        tools=registry,
        thresholds=_THRESHOLDS,
    )
    # Unknown tool → no AUTO_EXECUTE; no TOOL_CALL appended
    assert result.decisions[0].tool_call_event_appended is False


# ---------------------------------------------------------------------------
# fail-closed: unreachable host → MCPConnectionError/MCPTimeoutError
# ---------------------------------------------------------------------------


def test_remote_unreachable_host_tool_failed() -> None:
    """Unreachable streamable_http host → MCPConnectionError/MCPTimeoutError (fail-closed)."""
    transport = MCPTransport(
        "unreachable-remote",
        MCPServerConfig(
            transport="streamable_http",
            url="https://127.0.0.1:19998/mcp",
            tools={},
        ),
        MCPTimeouts(connect=0.5, list_tools=0.5, call_tool=0.5),
    )
    with pytest.raises((MCPConnectionError, MCPTimeoutError)):
        transport.call_tool("any_tool", {})


# ---------------------------------------------------------------------------
# fail-closed: auth failure → MCPConnectionError
# ---------------------------------------------------------------------------


def test_remote_auth_fail_tool_failed() -> None:
    """Auth failure from streamable_http server → MCPConnectionError (fail-closed)."""
    with patch(
        "orchestrator.mcp.transport.streamable_http_client",
        side_effect=httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        ),
    ):
        transport = MCPTransport(
            "auth-fail-remote",
            _remote_cfg(),
            MCPTimeouts(connect=1.0, list_tools=1.0, call_tool=1.0),
        )
        with pytest.raises(MCPConnectionError):
            transport.call_tool("any_tool", {})
