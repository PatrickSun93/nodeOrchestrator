"""Skill matcher: decide_skills_for_context.

Pure function — no I/O, no LLM calls. Accepts a pre-loaded skill registry
and returns a SkillSelection carrying the full decision trace.

Concurrency: §2 N/A — function is stateless; concurrent calls are safe.
"""

from __future__ import annotations

from orchestrator.core.event import EventType
from orchestrator.core.room import RoomType
from orchestrator.skills.schema import (
    Skill,
    SkillDecisionTrace,
    SkillMatchRecord,
    SkillSelection,
)


def decide_skills_for_context(
    agent_id: str,
    room_type: RoomType,
    room_state: str,
    *,
    available_skills: dict[str, Skill],
    triggering_event_type: EventType | None = None,  # P1.4+ hook; unused in P1.3
) -> SkillSelection:
    """Select skills that match the given context.

    Matching predicate (all three must hold):
    1. agent_id in skill.applies_to.agents OR "*" in skill.applies_to.agents.
    2. room_type in skill.applies_to.room_types.
    3. skill.applies_to.room_states is None OR room_state in skill.applies_to.room_states.

    Rejection reason is the first failing predicate (1 → 2 → 3). If all pass,
    rejection_reason is "matched".

    Selected skills are ordered by (-priority, id) — descending priority, then
    ascending id for ties (ADR-009 Decision 5: deterministic, portable, greppable).

    triggering_event_type is accepted but has no effect in P1.3 (P1.4+ hook).
    """
    _ = triggering_event_type  # explicitly unused in P1.3

    considered: list[SkillMatchRecord] = []
    matched_skills: list[Skill] = []

    for skill in available_skills.values():
        agent_ok = "*" in skill.applies_to.agents or agent_id in skill.applies_to.agents
        if not agent_ok:
            considered.append(
                SkillMatchRecord(skill_id=skill.id, rejection_reason="agent_mismatch")
            )
            continue

        room_type_ok = room_type in skill.applies_to.room_types
        if not room_type_ok:
            considered.append(
                SkillMatchRecord(skill_id=skill.id, rejection_reason="room_type_mismatch")
            )
            continue

        room_state_ok = (
            skill.applies_to.room_states is None or room_state in skill.applies_to.room_states
        )
        if not room_state_ok:
            considered.append(
                SkillMatchRecord(skill_id=skill.id, rejection_reason="room_state_mismatch")
            )
            continue

        considered.append(SkillMatchRecord(skill_id=skill.id, rejection_reason="matched"))
        matched_skills.append(skill)

    matched_skills.sort(key=lambda s: (-s.priority, s.id))

    selected_count = len(matched_skills)
    rejected_count = len(considered) - selected_count

    return SkillSelection(
        selected=matched_skills,
        trace=SkillDecisionTrace(
            considered=considered,
            selected_count=selected_count,
            rejected_count=rejected_count,
        ),
    )
