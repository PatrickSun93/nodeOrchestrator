"""End-to-end integration tests for the autonomy emission pipeline.

Exercises the full chain: load_tools_config (yaml → ToolMeta dict) →
emit_gate_decision (gate + event emission) → EventStore (SQLite append).
Uses the project's real tools.yaml.example so doc-spec drift fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.autonomy.emission import emit_gate_decision
from orchestrator.autonomy.scoring import (
    AutonomyScore,
    AutonomyTier,
    Operation,
    ThresholdConfig,
    UnknownToolError,
)
from orchestrator.core.event import EventType, RoomId
from orchestrator.core.event_store import EventStore
from orchestrator.llm.config_loader import load_tools_config

_EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "config"
_TOOLS_YAML = _EXAMPLES_DIR / "tools.yaml.example"

_OPERATOR = ThresholdConfig(threshold_auto=6, threshold_confirm=3, user_intent_modifier=0)


def _op(tool_id: str) -> Operation:
    return Operation(
        tool_id=tool_id,
        initiating_agent="agent:operator",
        user_explicit_intent=False,
    )


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_e2e_success_full_chain_read_file(event_store: EventStore, room_id: RoomId) -> None:
    """read_file (reversibility=10) clears auto threshold — decision event emitted."""
    tools = load_tools_config(_TOOLS_YAML)
    result = emit_gate_decision(
        _op("read_file"), tools, _OPERATOR, event_store, room_id=room_id, author="agent:operator"
    )
    assert isinstance(result, AutonomyScore)
    assert result.tier == AutonomyTier.AUTO_EXECUTE

    events = event_store.get_room_events(room_id)
    decision_events = [e for e in events if e.type == EventType.AUTONOMY_DECISION]
    refusal_events = [e for e in events if e.type == EventType.AUTONOMY_REFUSAL]
    assert len(decision_events) == 1
    assert len(refusal_events) == 0
    assert decision_events[0].metadata["operation_tool_id"] == "read_file"
    assert decision_events[0].metadata["tier"] == AutonomyTier.AUTO_EXECUTE.value


# ---------------------------------------------------------------------------
# Refusal path
# ---------------------------------------------------------------------------


def test_e2e_refusal_unknown_tool_emits_refusal_event(
    event_store: EventStore, room_id: RoomId
) -> None:
    """Registry-miss raises UnknownToolError and appends autonomy_refusal before raise."""
    tools = load_tools_config(_TOOLS_YAML)
    with pytest.raises(UnknownToolError) as exc_info:
        emit_gate_decision(
            _op("ghost_tool"),
            tools,
            _OPERATOR,
            event_store,
            room_id=room_id,
            author="agent:operator",
        )
    assert exc_info.value.tool_id == "ghost_tool"

    events = event_store.get_room_events(room_id)
    refusal_events = [e for e in events if e.type == EventType.AUTONOMY_REFUSAL]
    decision_events = [e for e in events if e.type == EventType.AUTONOMY_DECISION]
    assert len(refusal_events) == 1
    assert len(decision_events) == 0
    assert refusal_events[0].metadata["operation_tool_id"] == "ghost_tool"
    assert refusal_events[0].metadata["refusal_reason"] == "unknown_tool"
