"""§1 cross-module gating tests + §4 boundary/validation tests.

§1 discriminating:
  - MCP tool registered + AUTO_EXECUTE → TOOL_CALL event appended
  - MCP tool registered + HARD_CONFIRM → no TOOL_CALL event (gate blocks)
  - Unclassified MCP tool (not in allowlist) → UnknownToolError → refused
  - Server "safe" hint does NOT change tier (config reversibility wins, HR#2)
§4 boundary:
  - Undeclared server → refused (only allowlisted servers connectable, HR#7)
  - Namespacing collision-free: local tools never start with mcp__
  - adapter.to_mcp_call round-trip
  - build_tool_registry skips discovered-but-unclassified tools (HR#3)
  - Allowlisted-but-undiscovered tools also skipped (server doesn't expose)
"""

from __future__ import annotations

import sqlite3

import pytest
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
from orchestrator.mcp.adapter import (
    AdapterError,
    build_tool_registry,
    namespace,
    to_mcp_call,
)
from orchestrator.mcp.config import MCPServerConfig, MCPToolConfig

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_THRESHOLDS = ThresholdConfig(threshold_auto=7, threshold_confirm=3, user_intent_modifier=0)
# read_file: rev 10 → score 10 >= auto=7 → AUTO_EXECUTE
# write_file: rev 2 → score 2 < confirm=3 → HARD_CONFIRM (modifier=0 keeps thresholds exact)


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


def _tool_call(name: str, call_id: str = "tc_1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={})


def _make_mcp_tool(name: str) -> Tool:
    return Tool(name=name, inputSchema={"type": "object", "properties": {}})


# Pre-built local + MCP tool registry used in §1 tests
_MCP_SERVER_CFG = MCPServerConfig(
    command="npx",
    args=["-y", "test-server"],
    tools={
        "read_file": MCPToolConfig(reversibility=10),
        "write_file": MCPToolConfig(reversibility=2),
    },
)

_DISCOVERED_TOOLS = [
    _make_mcp_tool("read_file"),
    _make_mcp_tool("write_file"),
    _make_mcp_tool("unclassified_tool"),  # discovered but NOT in allowlist
]

_MCP_REGISTRY = build_tool_registry("filesystem", _MCP_SERVER_CFG, _DISCOVERED_TOOLS)

# Combined registry (local + MCP namespaced)
_LOCAL_TOOLS: dict[str, ToolMeta] = {
    "local_search": ToolMeta(reversibility=10),
}
_COMBINED_TOOLS: dict[str, ToolMeta] = {**_LOCAL_TOOLS, **_MCP_REGISTRY}


# ---------------------------------------------------------------------------
# §1 discriminating: gate tier for MCP tools
# ---------------------------------------------------------------------------


def test_gating_mcp_auto_execute_appends_tool_call_event() -> None:
    """mcp__filesystem__read_file (rev 10) → AUTO_EXECUTE → TOOL_CALL event appended."""
    store = _make_store()
    room_id = _make_room(store)
    event = _make_user_event(room_id)
    store.append(event)

    result = process_tool_calls(
        [_tool_call("mcp__filesystem__read_file")],
        agent_id="test",
        room_id=room_id,
        current_event=event,
        event_store=store,
        tools=_COMBINED_TOOLS,
        thresholds=_THRESHOLDS,
    )

    assert len(result.decisions) == 1
    d = result.decisions[0]
    assert d.tier == AutonomyTier.AUTO_EXECUTE
    assert d.tool_call_event_appended is True
    assert d.refusal_reason is None

    # TOOL_CALL event must be in the store
    events = store.get_room_events(room_id)
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].metadata["tool_name"] == "mcp__filesystem__read_file"


def test_gating_mcp_hard_confirm_no_tool_call_event() -> None:
    """mcp__filesystem__write_file (rev 2) → HARD_CONFIRM → no TOOL_CALL event."""
    store = _make_store()
    room_id = _make_room(store)
    event = _make_user_event(room_id)
    store.append(event)

    result = process_tool_calls(
        [_tool_call("mcp__filesystem__write_file")],
        agent_id="test",
        room_id=room_id,
        current_event=event,
        event_store=store,
        tools=_COMBINED_TOOLS,
        thresholds=_THRESHOLDS,
    )

    d = result.decisions[0]
    assert d.tier == AutonomyTier.HARD_CONFIRM
    assert d.tool_call_event_appended is False  # Gate blocks — MVP AUTO-only
    assert d.refusal_reason is None

    events = store.get_room_events(room_id)
    tool_call_events = [e for e in events if e.type == EventType.TOOL_CALL]
    assert not tool_call_events  # No TOOL_CALL event → not executed


def test_gating_mcp_unclassified_tool_refused() -> None:
    """Unclassified MCP tool (not in allowlist) → UnknownToolError → refused."""
    store = _make_store()
    room_id = _make_room(store)
    event = _make_user_event(room_id)
    store.append(event)

    # "mcp__filesystem__unclassified_tool" is not in _MCP_REGISTRY
    # (build_tool_registry skips it; HR#3 discovery≠permission)
    result = process_tool_calls(
        [_tool_call("mcp__filesystem__unclassified_tool")],
        agent_id="test",
        room_id=room_id,
        current_event=event,
        event_store=store,
        tools=_COMBINED_TOOLS,
        thresholds=_THRESHOLDS,
    )

    d = result.decisions[0]
    assert d.tier is None
    assert d.refusal_reason == "unknown_tool"
    assert d.tool_call_event_appended is False

    # autonomy_refusal event must be appended
    events = store.get_room_events(room_id)
    refusal_events = [e for e in events if e.type == EventType.AUTONOMY_REFUSAL]
    assert len(refusal_events) == 1


def test_gating_server_safe_hint_does_not_change_tier() -> None:
    """Server readOnlyHint:true on a low-rev tool must NOT change the tier (HR#2).

    The config reversibility wins; server hints are advisory-only.
    """
    # Tool with readOnlyHint=True but config reversibility=2 → HARD_CONFIRM
    # (If hints were trusted, it would become AUTO_EXECUTE — the wrong behavior.)
    server_cfg = MCPServerConfig(
        command="npx",
        args=["-y", "test-server"],
        tools={
            "tricky_tool": MCPToolConfig(reversibility=2),  # low-rev
        },
    )
    # The discovered tool has readOnlyHint=True (safe hint from server)
    # but we don't even look at it — adapter ignores hints
    from mcp.types import ToolAnnotations

    discovered = [
        Tool(
            name="tricky_tool",
            inputSchema={"type": "object"},
            annotations=ToolAnnotations(readOnlyHint=True),
        )
    ]
    registry = build_tool_registry("tricky_server", server_cfg, discovered)
    assert namespace("tricky_server", "tricky_tool") in registry
    tool_meta = registry[namespace("tricky_server", "tricky_tool")]
    # Reversibility must come from config (2), NOT from the safe hint
    assert tool_meta.reversibility == 2

    # Gate must produce HARD_CONFIRM for rev=2 with our thresholds
    store = _make_store()
    room_id = _make_room(store)
    event = _make_user_event(room_id)
    store.append(event)

    combined = {"local_x": ToolMeta(reversibility=10), **registry}
    result = process_tool_calls(
        [_tool_call("mcp__tricky_server__tricky_tool")],
        agent_id="test",
        room_id=room_id,
        current_event=event,
        event_store=store,
        tools=combined,
        thresholds=_THRESHOLDS,
    )
    assert result.decisions[0].tier == AutonomyTier.HARD_CONFIRM


# ---------------------------------------------------------------------------
# §4 boundary: adapter correctness
# ---------------------------------------------------------------------------


def test_adapter_namespace_format() -> None:
    """namespace() produces 'mcp__<server>__<tool>' (double-underscore)."""
    assert namespace("filesystem", "read_file") == "mcp__filesystem__read_file"
    assert namespace("github", "create_pr") == "mcp__github__create_pr"


def test_adapter_to_mcp_call_roundtrip() -> None:
    """to_mcp_call(namespace(s, t)) == (s, t) round-trip."""
    pairs = [
        ("filesystem", "read_file"),
        ("github", "create_pull_request"),
        ("my_server", "some_tool_name"),
    ]
    for server, tool in pairs:
        ns = namespace(server, tool)
        assert to_mcp_call(ns) == (server, tool)


def test_adapter_to_mcp_call_invalid_prefix() -> None:
    """to_mcp_call raises AdapterError for non-MCP-namespaced names."""
    with pytest.raises(AdapterError, match="Not an MCP-namespaced"):
        to_mcp_call("local_read_file")


def test_adapter_to_mcp_call_malformed() -> None:
    """to_mcp_call raises AdapterError for malformed mcp__ names."""
    with pytest.raises(AdapterError, match="Malformed"):
        to_mcp_call("mcp__only_one_part")  # missing second __
    with pytest.raises(AdapterError, match="Malformed"):
        to_mcp_call("mcp____empty_server")  # empty server name


def test_adapter_build_tool_registry_skips_unclassified() -> None:
    """Discovered-but-unclassified tools are NOT registered (HR#3)."""
    server_cfg = MCPServerConfig(
        command="npx",
        tools={
            "allowed_tool": MCPToolConfig(reversibility=10),
        },
    )
    discovered = [
        _make_mcp_tool("allowed_tool"),
        _make_mcp_tool("unclassified_tool"),  # not in allowlist
        _make_mcp_tool("another_unclassified"),
    ]
    registry = build_tool_registry("srv", server_cfg, discovered)

    assert namespace("srv", "allowed_tool") in registry
    assert namespace("srv", "unclassified_tool") not in registry
    assert namespace("srv", "another_unclassified") not in registry


def test_adapter_build_tool_registry_skips_allowlisted_not_discovered() -> None:
    """Allowlisted-but-not-discovered tools are also skipped (server doesn't expose)."""
    server_cfg = MCPServerConfig(
        command="npx",
        tools={
            "read_file": MCPToolConfig(reversibility=10),
            "phantom_tool": MCPToolConfig(reversibility=5),  # not discovered
        },
    )
    discovered = [_make_mcp_tool("read_file")]
    registry = build_tool_registry("srv", server_cfg, discovered)

    assert namespace("srv", "read_file") in registry
    assert namespace("srv", "phantom_tool") not in registry


def test_adapter_build_tool_registry_config_reversibility_used() -> None:
    """build_tool_registry uses config reversibility, not any server annotation."""
    server_cfg = MCPServerConfig(
        command="npx",
        tools={"my_tool": MCPToolConfig(reversibility=7)},
    )
    discovered = [_make_mcp_tool("my_tool")]
    registry = build_tool_registry("srv", server_cfg, discovered)

    key = namespace("srv", "my_tool")
    assert key in registry
    assert registry[key].reversibility == 7


def test_adapter_default_reversibility_zero_for_omitted() -> None:
    """Tool with reversibility omitted defaults to 0 (conservative-low, ADR-005 D2)."""
    from orchestrator.mcp.config import MCPToolConfig

    cfg = MCPToolConfig()  # no reversibility → default 0
    assert cfg.reversibility == 0

    server_cfg = MCPServerConfig(
        command="npx",
        tools={"omitted_rev": cfg},
    )
    discovered = [_make_mcp_tool("omitted_rev")]
    registry = build_tool_registry("srv", server_cfg, discovered)
    key = namespace("srv", "omitted_rev")
    assert registry[key].reversibility == 0


def test_boundary_undeclared_server_refused() -> None:
    """An MCP tool from an undeclared server → not in registry → refused (HR#7)."""
    # Only 'filesystem' is in the registry; 'evil_server' is not configured.
    store = _make_store()
    room_id = _make_room(store)
    event = _make_user_event(room_id)
    store.append(event)

    result = process_tool_calls(
        [_tool_call("mcp__evil_server__steal_data")],
        agent_id="test",
        room_id=room_id,
        current_event=event,
        event_store=store,
        tools=_COMBINED_TOOLS,  # evil_server not in this registry
        thresholds=_THRESHOLDS,
    )

    d = result.decisions[0]
    assert d.refusal_reason == "unknown_tool"
    assert d.tier is None
