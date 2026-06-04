"""Tests for ``orchestrator.rooms.templates``.

Covers:
1. Research template: loads skeptic + prober when present in available_agents.
2. Research template: operator/divergence_mapper/logger declared but missing
   → returned in missing list.
3. Research: missing-agent list is non-empty when not all declared agents
   are available.
4. Scaffold templates load with correct P3.1 rosters (not empty).
5. ``default_initial_state`` equals ``"setup"`` for all templates.
6. ``RoomTemplate`` schema invariants (frozen + extra-forbid).
7. ``load_room`` with empty available_agents returns all declared agents as missing
   (for Research and for each scaffold room per its P3.1 roster).

Agents are constructed synthetically (no yaml I/O) per plan §P1.5-6.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.agents.schema import Agent
from orchestrator.core.room import RoomType
from orchestrator.llm.types import AgentAutonomyThresholds, AgentLLMConfig, ModelId
from orchestrator.rooms.templates import ROOM_TEMPLATES, RoomTemplate, load_room

# ---------------------------------------------------------------------------
# Synthetic agent helpers
# ---------------------------------------------------------------------------

_AUTONOMY = AgentAutonomyThresholds(
    threshold_auto=8,
    threshold_confirm=4,
    user_intent_modifier=2,
)
_LLM = AgentLLMConfig(
    default_model=ModelId("m1"),
    autonomy_thresholds=_AUTONOMY,
)


def _make_agent(agent_id: str) -> Agent:
    """Return a minimal synthetic ``Agent`` for testing."""
    return Agent(id=agent_id, role="r", persona="p", llm_config=_LLM)


# ---------------------------------------------------------------------------
# §1 — Research template loads skeptic + prober when present
# ---------------------------------------------------------------------------


def test_load_room_research_skeptic_and_prober_present() -> None:
    """Research room: skeptic and prober in available_agents → not in missing."""
    available: dict[str, Agent] = {
        "skeptic": _make_agent("skeptic"),
        "prober": _make_agent("prober"),
    }
    room, missing = load_room(RoomType.RESEARCH, available)

    # skeptic and prober are present — they should NOT be in missing
    assert "skeptic" not in missing
    assert "prober" not in missing

    # The other 3 declared agents are absent
    assert "divergence_mapper" in missing
    assert "logger" in missing
    assert "operator" in missing

    # Room basic invariants
    assert room.type == RoomType.RESEARCH
    assert room.state == "setup"
    assert room.id.startswith("room_")


# ---------------------------------------------------------------------------
# §2 — operator / divergence_mapper / logger declared but missing
# ---------------------------------------------------------------------------


def test_load_room_research_three_absent_agents_in_missing_list() -> None:
    """operator, divergence_mapper, logger absent → each appears in missing list."""
    available: dict[str, Agent] = {
        "skeptic": _make_agent("skeptic"),
        "prober": _make_agent("prober"),
    }
    _, missing = load_room(RoomType.RESEARCH, available)

    assert set(missing) == {"divergence_mapper", "logger", "operator", "synthesizer"}


# ---------------------------------------------------------------------------
# §3 — missing list is non-empty when not all declared agents are available
# ---------------------------------------------------------------------------


def test_load_room_research_missing_list_nonempty_when_partial() -> None:
    """Research room: missing list is non-empty when only some agents available."""
    available: dict[str, Agent] = {
        "skeptic": _make_agent("skeptic"),
    }
    _, missing = load_room(RoomType.RESEARCH, available)

    assert len(missing) > 0
    # Exactly 5 declared agents are absent (all except skeptic)
    assert len(missing) == 5


# ---------------------------------------------------------------------------
# §4 — Scaffold templates load with correct P3.1 rosters
# ---------------------------------------------------------------------------

_SCAFFOLD_ROSTERS: dict[RoomType, list[str]] = {
    RoomType.BUG_FIX: ["logger", "operator", "prober", "skeptic"],
    RoomType.CODE_REVIEW: ["logger", "operator", "skeptic", "synthesizer"],
    RoomType.IDEA_VALIDATION: [
        "divergence_mapper",
        "logger",
        "operator",
        "prober",
        "skeptic",
        "synthesizer",
    ],
    RoomType.FREE_CHAT: ["facilitator", "logger"],
}


@pytest.mark.parametrize("room_type", list(_SCAFFOLD_ROSTERS))
def test_scaffold_templates_load_room_type_and_state(room_type: RoomType) -> None:
    """Each scaffold template constructs a Room with the correct type and initial state."""
    room, _ = load_room(room_type, {})

    assert room.type == room_type
    assert room.state == "setup"


@pytest.mark.parametrize("room_type", list(_SCAFFOLD_ROSTERS))
def test_scaffold_templates_declared_agents_per_p3_1_roster(room_type: RoomType) -> None:
    """Each scaffold template declares the P3.1 roster (alphabetical)."""
    template = ROOM_TEMPLATES[room_type]
    assert template.declared_agents == _SCAFFOLD_ROSTERS[room_type]


@pytest.mark.parametrize("room_type", list(_SCAFFOLD_ROSTERS))
def test_scaffold_templates_all_missing_when_no_agents_available(room_type: RoomType) -> None:
    """load_room with empty available_agents: missing == declared roster."""
    _, missing = load_room(room_type, {})
    assert missing == _SCAFFOLD_ROSTERS[room_type]


@pytest.mark.parametrize("room_type", list(_SCAFFOLD_ROSTERS))
def test_scaffold_templates_no_missing_when_all_declared_available(room_type: RoomType) -> None:
    """load_room with all declared agents present: missing == []."""
    roster = _SCAFFOLD_ROSTERS[room_type]
    available = {aid: _make_agent(aid) for aid in roster}
    _, missing = load_room(room_type, available)
    assert missing == []


# ---------------------------------------------------------------------------
# §5 — default_initial_state == "setup" for all templates
# ---------------------------------------------------------------------------


def test_all_templates_default_initial_state_is_setup() -> None:
    """Every RoomTemplate in ROOM_TEMPLATES has default_initial_state == 'setup'."""
    for room_type in RoomType:
        template = ROOM_TEMPLATES[room_type]
        assert template.default_initial_state == "setup", (
            f"{room_type.value} template has unexpected "
            f"default_initial_state={template.default_initial_state!r}"
        )


# ---------------------------------------------------------------------------
# §6 — RoomTemplate schema invariants (frozen + extra-forbid)
# ---------------------------------------------------------------------------


def test_room_template_is_frozen() -> None:
    """RoomTemplate instances are immutable (frozen=True)."""
    template = ROOM_TEMPLATES[RoomType.RESEARCH]
    with pytest.raises((TypeError, ValidationError)):
        template.default_initial_state = "exploration"


def test_room_template_extra_forbid() -> None:
    """RoomTemplate rejects unknown fields (extra='forbid')."""
    with pytest.raises(ValidationError):
        RoomTemplate(
            room_type=RoomType.RESEARCH,
            declared_agents=[],
            default_initial_state="setup",
            unknown_field="bad",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# §7 — load_room with empty available_agents
# ---------------------------------------------------------------------------


def test_load_room_empty_available_agents_returns_all_declared_as_missing() -> None:
    """load_room with empty available_agents returns empty room + all declared missing."""
    room, missing = load_room(RoomType.RESEARCH, {})

    template = ROOM_TEMPLATES[RoomType.RESEARCH]
    assert set(missing) == set(template.declared_agents)
    assert len(missing) == len(template.declared_agents)

    # Room is still valid despite all agents missing
    assert room.type == RoomType.RESEARCH
    assert room.state == "setup"


def test_load_room_empty_available_agents_scaffold_returns_full_roster_as_missing() -> None:
    """Scaffold load_room with empty available_agents: missing == full declared roster."""
    room, missing = load_room(RoomType.BUG_FIX, {})

    assert missing == ["logger", "operator", "prober", "skeptic"]
    assert room.type == RoomType.BUG_FIX
    assert room.state == "setup"


# ---------------------------------------------------------------------------
# Additional invariant tests
# ---------------------------------------------------------------------------


def test_room_templates_covers_all_room_types() -> None:
    """ROOM_TEMPLATES has an entry for every RoomType value."""
    for room_type in RoomType:
        assert room_type in ROOM_TEMPLATES, f"Missing template for {room_type.value!r}"


def test_research_declared_agents_are_alphabetical() -> None:
    """Research template declared_agents list is sorted alphabetically."""
    template = ROOM_TEMPLATES[RoomType.RESEARCH]
    assert template.declared_agents == sorted(template.declared_agents)


def test_research_declared_agents_count() -> None:
    """Research template declares exactly 6 agents."""
    template = ROOM_TEMPLATES[RoomType.RESEARCH]
    assert len(template.declared_agents) == 6


def test_load_room_each_room_type_gets_unique_id() -> None:
    """Each load_room call produces a Room with a unique id."""
    room1, _ = load_room(RoomType.RESEARCH, {})
    room2, _ = load_room(RoomType.RESEARCH, {})
    assert room1.id != room2.id


def test_load_room_missing_list_order_matches_declaration() -> None:
    """Missing agent ids are returned in declared (alphabetical) order."""
    # Provide only "skeptic" — the other 4 declared agents are missing
    available: dict[str, Agent] = {"skeptic": _make_agent("skeptic")}
    _, missing = load_room(RoomType.RESEARCH, available)

    template = ROOM_TEMPLATES[RoomType.RESEARCH]
    expected_missing = [aid for aid in template.declared_agents if aid != "skeptic"]
    assert missing == expected_missing
