"""Agent selector and per-agent context builder.

Two pure functions:
  - ``decide_agents_for_room``: returns all available agents in P1.4
    (room-type filtering deferred to P1.5+).
  - ``build_agent_context``: assembles the per-turn context fed to one
    agent's LLM call.

Both are pure (no I/O, no LLM calls).  Concurrency: §2 N/A — stateless.
"""

from __future__ import annotations

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
    *,
    available_agents: dict[str, Agent],
) -> AgentSelection:
    """Return the agents to load into a room.

    P1.4: returns ALL available agents — no room-type filtering.
    P1.5+ adds ``room_type`` and ``room_state`` parameters alongside
    the real ``agent.applies_to.room_types`` filtering logic.

    Selected agents are sorted **alphabetically by ``agent.id``
    ascending** (ADR-011 D3 revised — no ``priority`` field in P1.4).
    """
    records = [AgentMatchRecord(agent_id=a.id, loaded=True) for a in available_agents.values()]
    loaded = sorted(available_agents.values(), key=lambda a: a.id)
    return AgentSelection(
        loaded=loaded,
        trace=AgentSelectionTrace(
            considered=records,
            loaded_count=len(loaded),
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
