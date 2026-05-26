"""Tests for src/orchestrator/skills/decision.py.

Coverage-standard application:
  §1: cross-module integration test (Skill via schema → decide_skills_for_context
      → SkillSelection.selected) lives in test_integration.py (P1.3-6).
  §5: precedence of rejection_reason when multiple predicates fail.
"""

from __future__ import annotations

import pytest

from orchestrator.core.event import EventType
from orchestrator.core.room import RoomType
from orchestrator.skills.decision import decide_skills_for_context
from orchestrator.skills.schema import AppliesTo, Skill

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE_APPLIES_TO = AppliesTo(agents=["prober"], room_types=[RoomType.RESEARCH])


def _skill(
    sid: str,
    *,
    agents: list[str] | None = None,
    room_types: list[RoomType] | None = None,
    room_states: list[str] | None = None,
    priority: int = 50,
) -> Skill:
    return Skill(
        id=sid,
        category="general",
        applies_to=AppliesTo(
            agents=agents or ["prober"],
            room_types=room_types or [RoomType.RESEARCH],
            room_states=room_states,
        ),
        priority=priority,
        body="placeholder",
    )


# ---------------------------------------------------------------------------
# Basic matching
# ---------------------------------------------------------------------------


def test_matching_skill_selected() -> None:
    skills = {"research-skill": _skill("research-skill")}
    result = decide_skills_for_context("prober", RoomType.RESEARCH, "open", available_skills=skills)
    assert len(result.selected) == 1
    assert result.selected[0].id == "research-skill"
    assert result.trace.selected_count == 1
    assert result.trace.rejected_count == 0


def test_empty_skills_returns_empty() -> None:
    result = decide_skills_for_context("prober", RoomType.RESEARCH, "open", available_skills={})
    assert result.selected == []
    assert result.trace.considered == []
    assert result.trace.selected_count == 0
    assert result.trace.rejected_count == 0


def test_agent_mismatch_rejected() -> None:
    skills = {"prober-skill": _skill("prober-skill", agents=["prober"])}
    result = decide_skills_for_context(
        "skeptic", RoomType.RESEARCH, "open", available_skills=skills
    )
    assert result.selected == []
    assert result.trace.considered[0].rejection_reason == "agent_mismatch"


def test_room_type_mismatch_rejected() -> None:
    skills = {"research-skill": _skill("research-skill", room_types=[RoomType.RESEARCH])}
    result = decide_skills_for_context("prober", RoomType.BUG_FIX, "open", available_skills=skills)
    assert result.selected == []
    assert result.trace.considered[0].rejection_reason == "room_type_mismatch"


def test_room_state_mismatch_rejected() -> None:
    skills = {
        "open-skill": _skill("open-skill", room_states=["open"]),
    }
    result = decide_skills_for_context(
        "prober", RoomType.RESEARCH, "closed", available_skills=skills
    )
    assert result.selected == []
    assert result.trace.considered[0].rejection_reason == "room_state_mismatch"


def test_room_states_none_matches_any_state() -> None:
    skills = {"any-state-skill": _skill("any-state-skill", room_states=None)}
    for state in ("open", "closed", "archived", "whatever"):
        result = decide_skills_for_context(
            "prober", RoomType.RESEARCH, state, available_skills=skills
        )
        assert result.selected[0].id == "any-state-skill", f"state={state!r} should match"


def test_explicit_room_state_only_matches_listed_state() -> None:
    skills = {"open-skill": _skill("open-skill", room_states=["open"])}

    matched = decide_skills_for_context(
        "prober", RoomType.RESEARCH, "open", available_skills=skills
    )
    assert matched.selected[0].id == "open-skill"

    not_matched = decide_skills_for_context(
        "prober", RoomType.RESEARCH, "closed", available_skills=skills
    )
    assert not_matched.selected == []


# ---------------------------------------------------------------------------
# agents ["*"] sentinel
# ---------------------------------------------------------------------------


def test_star_agents_matches_any_agent() -> None:
    skills = {"universal": _skill("universal", agents=["*"])}
    for agent in ("prober", "skeptic", "operator", "anyone"):
        result = decide_skills_for_context(
            agent, RoomType.RESEARCH, "open", available_skills=skills
        )
        assert result.selected[0].id == "universal", f"agent={agent!r} should match"


# ---------------------------------------------------------------------------
# All 5 RoomType values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "room_type",
    [
        RoomType.FREE_CHAT,
        RoomType.BUG_FIX,
        RoomType.RESEARCH,
        RoomType.CODE_REVIEW,
        RoomType.IDEA_VALIDATION,
    ],
)
def test_all_room_types_can_match(room_type: RoomType) -> None:
    skills = {
        "any-room": _skill("any-room", room_types=[room_type]),
    }
    result = decide_skills_for_context("prober", room_type, "open", available_skills=skills)
    assert result.selected[0].id == "any-room"


# ---------------------------------------------------------------------------
# §5 rejection_reason precedence
# ---------------------------------------------------------------------------


def test_agent_mismatch_takes_precedence_over_room_type_mismatch() -> None:
    """When both agent AND room_type fail, rejection_reason is agent_mismatch (predicate 1 first)."""
    skills = {
        "specific-skill": _skill(
            "specific-skill",
            agents=["prober"],
            room_types=[RoomType.RESEARCH],
        )
    }
    result = decide_skills_for_context("skeptic", RoomType.BUG_FIX, "open", available_skills=skills)
    assert result.trace.considered[0].rejection_reason == "agent_mismatch"


def test_room_type_mismatch_takes_precedence_over_room_state_mismatch() -> None:
    """When room_type AND room_state both fail, room_type_mismatch is reported (predicate 2 first)."""
    skills = {
        "room-skill": _skill(
            "room-skill",
            room_types=[RoomType.RESEARCH],
            room_states=["open"],
        )
    }
    result = decide_skills_for_context(
        "prober", RoomType.BUG_FIX, "closed", available_skills=skills
    )
    assert result.trace.considered[0].rejection_reason == "room_type_mismatch"


# ---------------------------------------------------------------------------
# Priority tie-breaking
# ---------------------------------------------------------------------------


def test_priority_ordering_descending() -> None:
    skills = {
        "low": _skill("low", priority=30),
        "high": _skill("high", priority=80),
        "mid": _skill("mid", priority=50),
    }
    result = decide_skills_for_context("prober", RoomType.RESEARCH, "open", available_skills=skills)
    assert [s.id for s in result.selected] == ["high", "mid", "low"]


def test_priority_tie_broken_alphabetically() -> None:
    skills = {
        "zebra-skill": _skill("zebra-skill", priority=50),
        "apple-skill": _skill("apple-skill", priority=50),
        "mango-skill": _skill("mango-skill", priority=50),
    }
    result = decide_skills_for_context("prober", RoomType.RESEARCH, "open", available_skills=skills)
    assert [s.id for s in result.selected] == ["apple-skill", "mango-skill", "zebra-skill"]


# ---------------------------------------------------------------------------
# triggering_event_type has no effect in P1.3
# ---------------------------------------------------------------------------


def test_triggering_event_type_none_and_non_none_produce_identical_output() -> None:
    skills = {"skill-a": _skill("skill-a")}
    r_none = decide_skills_for_context(
        "prober",
        RoomType.RESEARCH,
        "open",
        available_skills=skills,
        triggering_event_type=None,
    )
    r_event = decide_skills_for_context(
        "prober",
        RoomType.RESEARCH,
        "open",
        available_skills=skills,
        triggering_event_type=EventType.UTTERANCE,
    )
    assert r_none.selected == r_event.selected
    assert r_none.trace == r_event.trace


# ---------------------------------------------------------------------------
# Trace correctness
# ---------------------------------------------------------------------------


def test_trace_counts_match_considered_list() -> None:
    skills = {
        "match1": _skill("match1"),
        "match2": _skill("match2"),
        "reject1": _skill("reject1", agents=["other-agent"]),
    }
    result = decide_skills_for_context("prober", RoomType.RESEARCH, "open", available_skills=skills)
    assert result.trace.selected_count == 2
    assert result.trace.rejected_count == 1
    assert len(result.trace.considered) == 3


def test_matched_records_derive_from_rejection_reason() -> None:
    """No matched: bool field — derive from rejection_reason == "matched"."""
    skills = {"s": _skill("s")}
    result = decide_skills_for_context("prober", RoomType.RESEARCH, "open", available_skills=skills)
    record = result.trace.considered[0]
    assert record.rejection_reason == "matched"
    assert not hasattr(record, "matched")
