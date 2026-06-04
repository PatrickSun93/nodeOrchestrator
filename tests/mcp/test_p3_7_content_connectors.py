"""Discriminating tests for P3.7-content new local connectors (P3.7-content-8..9).

Per plan §2 Common acceptance bar (mirror tests/mcp/test_gating.py):
  - classified read tool (rev 10) → AUTO_EXECUTE (tier discrimination)
  - classified write/mutation tool (low rev) → HARD_CONFIRM (tier discrimination)
  - tool exposed by server but NOT in allowlist → UnknownToolError → refused (HR#3)
  - config validates against frozen MCPServerConfig schema

Tests gate config/classification only — no live npx subprocess.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mcp.types import Tool

from orchestrator.agents.tool_dispatch import process_tool_calls
from orchestrator.autonomy.scoring import AutonomyTier, ThresholdConfig, ToolMeta
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.types import ToolCall
from orchestrator.mcp.adapter import build_tool_registry, namespace
from orchestrator.mcp.config import (
    MCPServerConfig,
    MCPToolConfig,
    load_mcp_servers_config,
)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "mcp_servers.yaml"

# Thresholds: rev 10 → AUTO_EXECUTE; rev 1-2 → HARD_CONFIRM
_THRESHOLDS = ThresholdConfig(threshold_auto=7, threshold_confirm=3, user_intent_modifier=0)


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:")
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room(store: EventStore) -> RoomId:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


def _make_user_event(room_id: RoomId) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.USER_INPUT,
        author="user",
        timestamp=now_ms(),
        content="please run the tool",
    )


def _tool_call(name: str) -> ToolCall:
    return ToolCall(id="tc_1", name=name, arguments={})


def _make_mcp_tool(name: str) -> Tool:
    return Tool(name=name, inputSchema={"type": "object", "properties": {}})


# ---------------------------------------------------------------------------
# P3.7-content-8: memory connector
# ---------------------------------------------------------------------------


class TestMemoryConnector:
    """Discriminating tests for the memory connector (P3.7-content-8)."""

    def setup_method(self) -> None:
        # Build registry from config + simulated discovered tools
        # (includes delete_entities as exposed-but-unlisted)
        server_cfg = MCPServerConfig(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-memory"],
            tools={
                "read_graph": MCPToolConfig(reversibility=10),
                "search_nodes": MCPToolConfig(reversibility=10),
                "create_entities": MCPToolConfig(reversibility=1),
            },
        )
        discovered = [
            _make_mcp_tool("read_graph"),
            _make_mcp_tool("search_nodes"),
            _make_mcp_tool("create_entities"),
            _make_mcp_tool("delete_entities"),  # exposed but NOT in allowlist
        ]
        self.registry = build_tool_registry("memory", server_cfg, discovered)
        self.combined: dict[str, ToolMeta] = {**self.registry}

    def test_memory_config_loads_from_yaml(self) -> None:
        """memory server entry loads from config/mcp_servers.yaml."""
        cfg = load_mcp_servers_config(_CONFIG_PATH)
        assert "memory" in cfg.servers
        srv = cfg.servers["memory"]
        assert "read_graph" in srv.tools
        assert "search_nodes" in srv.tools
        assert "create_entities" in srv.tools

    def test_memory_config_validates_frozen_schema(self) -> None:
        """memory server config validates against frozen MCPServerConfig schema."""
        cfg = load_mcp_servers_config(_CONFIG_PATH)
        srv = cfg.servers["memory"]
        assert isinstance(srv, MCPServerConfig)

    def test_read_graph_rev10_auto_execute(self) -> None:
        """memory read_graph (rev 10) → AUTO_EXECUTE."""
        store = _make_store()
        room_id = _make_room(store)
        event = _make_user_event(room_id)
        store.append(event)

        result = process_tool_calls(
            [_tool_call("mcp__memory__read_graph")],
            agent_id="test",
            room_id=room_id,
            current_event=event,
            event_store=store,
            tools=self.combined,
            thresholds=_THRESHOLDS,
        )
        assert result.decisions[0].tier == AutonomyTier.AUTO_EXECUTE

    def test_search_nodes_rev10_auto_execute(self) -> None:
        """memory search_nodes (rev 10) → AUTO_EXECUTE (tier discrimination)."""
        store = _make_store()
        room_id = _make_room(store)
        event = _make_user_event(room_id)
        store.append(event)

        result = process_tool_calls(
            [_tool_call("mcp__memory__search_nodes")],
            agent_id="test",
            room_id=room_id,
            current_event=event,
            event_store=store,
            tools=self.combined,
            thresholds=_THRESHOLDS,
        )
        assert result.decisions[0].tier == AutonomyTier.AUTO_EXECUTE

    def test_create_entities_low_rev_hard_confirm(self) -> None:
        """memory create_entities (rev 1) → HARD_CONFIRM (tier discrimination)."""
        store = _make_store()
        room_id = _make_room(store)
        event = _make_user_event(room_id)
        store.append(event)

        result = process_tool_calls(
            [_tool_call("mcp__memory__create_entities")],
            agent_id="test",
            room_id=room_id,
            current_event=event,
            event_store=store,
            tools=self.combined,
            thresholds=_THRESHOLDS,
        )
        assert result.decisions[0].tier == AutonomyTier.HARD_CONFIRM
        assert result.decisions[0].tool_call_event_appended is False

    def test_delete_entities_unlisted_refused(self) -> None:
        """delete_entities not in allowlist → UnknownToolError → refused (HR#3)."""
        # delete_entities is NOT in self.registry (build_tool_registry skips unlisted)
        assert namespace("memory", "delete_entities") not in self.registry

        store = _make_store()
        room_id = _make_room(store)
        event = _make_user_event(room_id)
        store.append(event)

        result = process_tool_calls(
            [_tool_call("mcp__memory__delete_entities")],
            agent_id="test",
            room_id=room_id,
            current_event=event,
            event_store=store,
            tools=self.combined,
            thresholds=_THRESHOLDS,
        )
        assert result.decisions[0].tier is None
        assert result.decisions[0].refusal_reason == "unknown_tool"


# ---------------------------------------------------------------------------
# P3.7-content-9: sqlite connector
# ---------------------------------------------------------------------------


class TestSqliteConnector:
    """Discriminating tests for the sqlite connector (P3.7-content-9)."""

    def setup_method(self) -> None:
        server_cfg = MCPServerConfig(
            command="uvx",
            args=["mcp-server-sqlite", "--db-path", "/tmp/test.db"],
            tools={
                "read_query": MCPToolConfig(reversibility=10),
                "list_tables": MCPToolConfig(reversibility=10),
                "write_query": MCPToolConfig(reversibility=1),
                "create_table": MCPToolConfig(reversibility=2),
            },
        )
        discovered = [
            _make_mcp_tool("read_query"),
            _make_mcp_tool("list_tables"),
            _make_mcp_tool("write_query"),
            _make_mcp_tool("create_table"),
            _make_mcp_tool("drop_table"),  # exposed but NOT in allowlist
        ]
        self.registry = build_tool_registry("sqlite", server_cfg, discovered)
        self.combined: dict[str, ToolMeta] = {**self.registry}

    def test_sqlite_config_loads_from_yaml(self) -> None:
        """sqlite server entry loads from config/mcp_servers.yaml."""
        cfg = load_mcp_servers_config(_CONFIG_PATH)
        assert "sqlite" in cfg.servers
        srv = cfg.servers["sqlite"]
        assert "read_query" in srv.tools
        assert "list_tables" in srv.tools
        assert "write_query" in srv.tools
        assert "create_table" in srv.tools

    def test_sqlite_config_validates_frozen_schema(self) -> None:
        """sqlite server config validates against frozen MCPServerConfig schema."""
        cfg = load_mcp_servers_config(_CONFIG_PATH)
        srv = cfg.servers["sqlite"]
        assert isinstance(srv, MCPServerConfig)

    def test_read_query_rev10_auto_execute(self) -> None:
        """sqlite read_query (rev 10) → AUTO_EXECUTE."""
        store = _make_store()
        room_id = _make_room(store)
        event = _make_user_event(room_id)
        store.append(event)

        result = process_tool_calls(
            [_tool_call("mcp__sqlite__read_query")],
            agent_id="test",
            room_id=room_id,
            current_event=event,
            event_store=store,
            tools=self.combined,
            thresholds=_THRESHOLDS,
        )
        assert result.decisions[0].tier == AutonomyTier.AUTO_EXECUTE

    def test_list_tables_rev10_auto_execute(self) -> None:
        """sqlite list_tables (rev 10) → AUTO_EXECUTE (tier discrimination)."""
        store = _make_store()
        room_id = _make_room(store)
        event = _make_user_event(room_id)
        store.append(event)

        result = process_tool_calls(
            [_tool_call("mcp__sqlite__list_tables")],
            agent_id="test",
            room_id=room_id,
            current_event=event,
            event_store=store,
            tools=self.combined,
            thresholds=_THRESHOLDS,
        )
        assert result.decisions[0].tier == AutonomyTier.AUTO_EXECUTE

    def test_write_query_low_rev_hard_confirm(self) -> None:
        """sqlite write_query (rev 1) → HARD_CONFIRM (tier discrimination)."""
        store = _make_store()
        room_id = _make_room(store)
        event = _make_user_event(room_id)
        store.append(event)

        result = process_tool_calls(
            [_tool_call("mcp__sqlite__write_query")],
            agent_id="test",
            room_id=room_id,
            current_event=event,
            event_store=store,
            tools=self.combined,
            thresholds=_THRESHOLDS,
        )
        assert result.decisions[0].tier == AutonomyTier.HARD_CONFIRM
        assert result.decisions[0].tool_call_event_appended is False

    def test_create_table_low_rev_hard_confirm(self) -> None:
        """sqlite create_table (rev 2) → HARD_CONFIRM."""
        store = _make_store()
        room_id = _make_room(store)
        event = _make_user_event(room_id)
        store.append(event)

        result = process_tool_calls(
            [_tool_call("mcp__sqlite__create_table")],
            agent_id="test",
            room_id=room_id,
            current_event=event,
            event_store=store,
            tools=self.combined,
            thresholds=_THRESHOLDS,
        )
        assert result.decisions[0].tier == AutonomyTier.HARD_CONFIRM

    def test_drop_table_unlisted_refused(self) -> None:
        """drop_table not in allowlist → UnknownToolError → refused (HR#3)."""
        assert namespace("sqlite", "drop_table") not in self.registry

        store = _make_store()
        room_id = _make_room(store)
        event = _make_user_event(room_id)
        store.append(event)

        result = process_tool_calls(
            [_tool_call("mcp__sqlite__drop_table")],
            agent_id="test",
            room_id=room_id,
            current_event=event,
            event_store=store,
            tools=self.combined,
            thresholds=_THRESHOLDS,
        )
        assert result.decisions[0].tier is None
        assert result.decisions[0].refusal_reason == "unknown_tool"
