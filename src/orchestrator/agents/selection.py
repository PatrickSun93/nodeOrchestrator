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

    ``snapshot`` is accepted as the per-turn snapshot (ADR-011 D2 invariant)
    but is not read in P1.4 — only the skill bodies are populated.  P1.5+
    will use the snapshot for ``snapshot_excerpt`` once that field lands
    on ``AgentContext``.

    ``skill_bodies`` ordering follows ADR-009 D5: skills are selected by
    ``decide_skills_for_context`` in descending priority then ascending id
    order; we take ``SkillSelection.selected`` in that order.
    """
    _ = snapshot  # explicitly unused in P1.4 (no snapshot_excerpt field yet)
    skill_selection = decide_skills_for_context(
        agent.id,
        room_type,
        room_state,
        available_skills=available_skills,
        triggering_event_type=EventType.UTTERANCE,
    )
    skill_bodies = [s.body for s in skill_selection.selected]
    return AgentContext(agent=agent, skill_bodies=skill_bodies)
