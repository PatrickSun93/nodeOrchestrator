"""Agent selector and per-agent context builder.

Two pure functions:
  - ``decide_agents_for_room``: load-time agent filtering by room type
    (P1.5; room-state dispatch-time filtering deferred to P1.5-7 RoomRuntime).
  - ``build_agent_context``: assembles the per-turn context fed to one
    agent's LLM call.

Both are pure (no I/O, no LLM calls).  Concurrency: §2 N/A — stateless.
"""

from __future__ import annotations

from typing import Literal

from orchestrator.agents.schema import (
    Agent,
    AgentContext,
    AgentMatchRecord,
    AgentSelection,
    AgentSelectionTrace,
)
from orchestrator.core.event import Event, EventType
from orchestrator.core.room import RoomType
from orchestrator.skills.decision import decide_skills_for_context
from orchestrator.skills.schema import Skill

# ADR-033 D2/D6: bounded recent-event slice for the snapshot_excerpt context field.
# Caps the excerpt injected into the dispatch_turn LLM prompt (system block).
MAX_SNAPSHOT_EXCERPT_CHARS: int = 8_000


def decide_agents_for_room(
    room_type: RoomType,
    room_state: str,
    *,
    available_agents: dict[str, Agent],
) -> AgentSelection:
    """Return the agents to load into a room.

    Load-time filter: an agent is loaded iff its ``applies_to.room_types``
    is ``["*"]`` (matches every room type) or contains ``room_type.value``.

    ``room_state`` param accepted but unused for load-time filtering
    (dispatch-time filtering happens in RoomRuntime).

    Selected agents are sorted **alphabetically by ``agent.id``
    ascending** (ADR-011 D3 revised — no ``priority`` field in P1.4).
    """
    _ = room_state  # reserved for dispatch-time filtering in P1.5-7 RoomRuntime
    records: list[AgentMatchRecord] = []
    loaded: list[Agent] = []

    for agent in available_agents.values():
        rt = agent.applies_to.room_types
        match = rt == ["*"] or room_type.value in rt
        reason: Literal["room_type_match", "room_type_mismatch"] = (
            "room_type_match" if match else "room_type_mismatch"
        )
        records.append(
            AgentMatchRecord(
                agent_id=agent.id,
                loaded=match,
                applies_to_match=match,
                reason=reason,
            )
        )
        if match:
            loaded.append(agent)

    loaded_sorted = sorted(loaded, key=lambda a: a.id)
    return AgentSelection(
        loaded=loaded_sorted,
        trace=AgentSelectionTrace(
            considered=records,
            loaded_count=len(loaded_sorted),
        ),
    )


_EXCERPT_EVENT_TYPES = frozenset(
    {
        EventType.USER_INPUT,
        EventType.UTTERANCE,
        EventType.TOOL_RESULT,
        EventType.TOOL_FAILED,
        EventType.OBSERVATION,
    }
)


def _mcp_tool_result_call_ids(snapshot: list[Event]) -> frozenset[str]:
    """Return call_ids of TOOL_CALL events whose tool_name starts with 'mcp__'.

    These identify TOOL_RESULT events that carry raw untrusted external bytes —
    the OBSERVATION (from the interpret step) is the trusted view to render
    instead (ADR-033 D6 R2-N1).
    """
    return frozenset(
        str(e.metadata.get("call_id", ""))
        for e in snapshot
        if e.type == EventType.TOOL_CALL
        and str(e.metadata.get("tool_name", "")).startswith("mcp__")
    )


def _render_snapshot_excerpt(snapshot: list[Event]) -> str | None:
    """Render the most-recent relevant events as a bounded excerpt string.

    Iterates from the NEWEST event backwards, accumulating lines until
    MAX_SNAPSHOT_EXCERPT_CHARS is reached. Returns None if snapshot is empty
    or no relevant events exist.

    Rendered as: ``[<type>] <author>: <content>``
    Events truncated to fit within the budget.

    Trust framing (ADR-033 D6 R2-N1): raw MCP TOOL_RESULT events (untrusted
    external bytes) are NOT rendered — use the paired OBSERVATION (interpreted/
    trusted view) instead.  Local-tool TOOL_RESULT events (trusted, our own
    code) are rendered.  ADR-033 D2/D6 / ADR-011 amendment.
    """
    mcp_result_ids = _mcp_tool_result_call_ids(snapshot)
    relevant = [
        e for e in snapshot
        if e.type in _EXCERPT_EVENT_TYPES
        and not (
            e.type == EventType.TOOL_RESULT
            and str(e.metadata.get("call_id", "")) in mcp_result_ids
        )
    ]
    if not relevant:
        return None

    lines: list[str] = []
    chars_used = 0
    for event in reversed(relevant):
        content = (event.content or "").strip()
        line = f"[{event.type.value}] {event.author}: {content}"
        line_chars = len(line) + 1  # +1 for newline
        if chars_used + line_chars > MAX_SNAPSHOT_EXCERPT_CHARS:
            break
        lines.append(line)
        chars_used += line_chars

    if not lines:
        return None
    # Reverse to chronological order (we collected newest-first).
    lines.reverse()
    return "\n".join(lines)


def build_agent_context(
    agent: Agent,
    room_type: RoomType,
    room_state: str,
    *,
    available_skills: dict[str, Skill],
    snapshot: list[Event],
) -> AgentContext:
    """Build the per-turn context for one agent.

    Pure function; no I/O, no LLM.  Calls ``decide_skills_for_context``
    and assembles the selected skills' bodies into ``AgentContext.skill_bodies``.

    P4.1 populates ``snapshot_excerpt`` from the snapshot (bounded by
    ``MAX_SNAPSHOT_EXCERPT_CHARS``), resolving the P1.4 deferral (ADR-033 D2/D6
    + the ADR-011 substantive amendment).

    ``skill_bodies`` ordering follows ADR-009 D5: skills are selected by
    ``decide_skills_for_context`` in descending priority then ascending id
    order; we take ``SkillSelection.selected`` in that order.
    """
    skill_selection = decide_skills_for_context(
        agent.id,
        room_type,
        room_state,
        available_skills=available_skills,
        triggering_event_type=EventType.UTTERANCE,
    )
    skill_bodies = [s.body for s in skill_selection.selected]
    excerpt = _render_snapshot_excerpt(snapshot)
    return AgentContext(agent=agent, skill_bodies=skill_bodies, snapshot_excerpt=excerpt)
