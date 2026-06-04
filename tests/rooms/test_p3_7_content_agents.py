"""Discriminating activation tests for P3.7-content new agents (P3.7-content-1..4).

Per plan §2 Common acceptance bar:
  - yaml validates against frozen Agent schema (extra="forbid")
  - applies_to.room_states non-empty (["*"] ok)
  - should_agent_speak returns speak=True on a constructed event in EACH declared room type
  - load_room(<non-declared type>) reports the agent ABSENT from the roster (present/missing
    partition)

Each agent also has a specific trigger: if the trigger type fires, the agent speaks.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.agents.loader import load_agents
from orchestrator.agents.schema import Agent
from orchestrator.agents.selection import decide_agents_for_room
from orchestrator.agents.speaking import should_agent_speak
from orchestrator.core.event import (
    Event,
    EventType,
    StateTransitionMeta,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.room import RoomType
from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import (
    Capability,
    ModelId,
    ModelProfile,
    ProviderId,
)
from orchestrator.rooms.templates import ROOM_TEMPLATES

# ---------------------------------------------------------------------------
# Module-level setup (shared with test_scaffold_activation.py pattern)
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config" / "agents"
_PROVIDER = ProviderId("test_provider")

_CAPS: dict[str, list[Capability]] = {
    "deepseek_v4_flash": [Capability.TOOLS],
    "qwen_mlx_30b": [Capability.TOOLS],
    "claude_code_opus_47": [Capability.EFFORT],
    "claude_code_sonnet_46": [Capability.EFFORT],
    "claude_code_haiku_45": [],
    "deepseek_v4_pro": [],
}


def _build_model_registry() -> ModelRegistry:
    profiles = {
        ModelId(mid): ModelProfile(
            id=ModelId(mid),
            provider=_PROVIDER,
            provider_model_id=mid,
            capabilities=_CAPS.get(mid, []),
            context_window=8192,
        )
        for mid in _CAPS
    }
    return ModelRegistry(profiles)


_MODELS = _build_model_registry()
_ALL_AGENTS, _REGEX_REGISTRY = load_agents(_CONFIG_DIR, models=_MODELS)

_ROOM_ID = generate_room_id()


def _room_agents(room_type: RoomType) -> dict[str, Agent]:
    sel = decide_agents_for_room(room_type, "setup", available_agents=_ALL_AGENTS)
    return {a.id: a for a in sel.loaded}


def _ev(event_type: EventType, *, content: str = "safe content") -> Event:
    return Event(
        id=generate_event_id(),
        room_id=_ROOM_ID,
        type=event_type,
        author="user",
        timestamp=now_ms(),
        content=content,
        metadata={},
    )


def _st_ev(*, new_state: str, prior_state: str) -> Event:
    meta = StateTransitionMeta(new_state=new_state, prior_state=prior_state)
    return Event(
        id=generate_event_id(),
        room_id=_ROOM_ID,
        type=EventType.STATE_TRANSITION,
        author="system",
        timestamp=now_ms(),
        content="",
        metadata=meta.model_dump(),
    )


def _speaks(agent: Agent, event: Event) -> bool:
    return should_agent_speak(agent, [], current_event=event, regex_registry=_REGEX_REGISTRY).speak


# ---------------------------------------------------------------------------
# P3.7-content-1: synthesizer (research, code_review, idea_validation)
# ---------------------------------------------------------------------------


class TestSynthesizerAgent:
    """Discriminating tests for the synthesizer agent (P3.7-content-1)."""

    def setup_method(self) -> None:
        self.agent = _ALL_AGENTS["synthesizer"]

    # Schema validation
    def test_synthesizer_loaded_as_valid_agent(self) -> None:
        """synthesizer.yaml loads and is a valid Agent instance."""
        assert isinstance(self.agent, Agent)
        assert self.agent.id == "synthesizer"
        assert self.agent.role == "synthesizer"

    def test_synthesizer_applies_to_room_states_non_empty(self) -> None:
        """synthesizer.applies_to.room_states is non-empty (["*"])."""
        assert len(self.agent.applies_to.room_states) >= 1

    # Present in declared room types
    def test_synthesizer_present_in_research_roster(self) -> None:
        """synthesizer in research declared_agents."""
        assert "synthesizer" in ROOM_TEMPLATES[RoomType.RESEARCH].declared_agents

    def test_synthesizer_present_in_code_review_roster(self) -> None:
        """synthesizer in code_review declared_agents."""
        assert "synthesizer" in ROOM_TEMPLATES[RoomType.CODE_REVIEW].declared_agents

    def test_synthesizer_present_in_idea_validation_roster(self) -> None:
        """synthesizer in idea_validation declared_agents."""
        assert "synthesizer" in ROOM_TEMPLATES[RoomType.IDEA_VALIDATION].declared_agents

    # Activation: speak=True in each declared room type on DECISION event
    def test_synthesizer_speaks_on_decision_in_research(self) -> None:
        """synthesizer speaks on DECISION event when loaded for research."""
        agents = _room_agents(RoomType.RESEARCH)
        assert "synthesizer" in agents
        ev = _ev(EventType.DECISION, content="ready to converge")
        assert _speaks(agents["synthesizer"], ev) is True

    def test_synthesizer_speaks_on_decision_in_code_review(self) -> None:
        """synthesizer speaks on DECISION event when loaded for code_review."""
        agents = _room_agents(RoomType.CODE_REVIEW)
        assert "synthesizer" in agents
        ev = _ev(EventType.DECISION, content="ready to converge")
        assert _speaks(agents["synthesizer"], ev) is True

    def test_synthesizer_speaks_on_decision_in_idea_validation(self) -> None:
        """synthesizer speaks on DECISION event when loaded for idea_validation."""
        agents = _room_agents(RoomType.IDEA_VALIDATION)
        assert "synthesizer" in agents
        ev = _ev(EventType.DECISION, content="ready to converge")
        assert _speaks(agents["synthesizer"], ev) is True

    # Absent from non-declared room type (present/missing partition)
    def test_synthesizer_absent_from_bug_fix_roster(self) -> None:
        """synthesizer NOT in bug_fix declared_agents (non-declared room)."""
        assert "synthesizer" not in ROOM_TEMPLATES[RoomType.BUG_FIX].declared_agents
        assert "synthesizer" not in _room_agents(RoomType.BUG_FIX)

    def test_synthesizer_absent_from_free_chat_roster(self) -> None:
        """synthesizer NOT in free_chat declared_agents (non-declared room)."""
        assert "synthesizer" not in ROOM_TEMPLATES[RoomType.FREE_CHAT].declared_agents
        assert "synthesizer" not in _room_agents(RoomType.FREE_CHAT)


# ---------------------------------------------------------------------------
# P3.7-content-2: planner (bug_fix, code_review, idea_validation)
# ---------------------------------------------------------------------------


class TestPlannerAgent:
    """Discriminating tests for the planner agent (P3.7-content-2)."""

    def setup_method(self) -> None:
        self.agent = _ALL_AGENTS["planner"]

    # Schema validation
    def test_planner_loaded_as_valid_agent(self) -> None:
        """planner.yaml loads and is a valid Agent instance."""
        assert isinstance(self.agent, Agent)
        assert self.agent.id == "planner"
        assert self.agent.role == "planner"

    def test_planner_applies_to_room_states_non_empty(self) -> None:
        """planner.applies_to.room_states is non-empty."""
        assert len(self.agent.applies_to.room_states) >= 1

    # Present in declared room types
    def test_planner_present_in_bug_fix_roster(self) -> None:
        """planner in bug_fix declared_agents."""
        assert "planner" in ROOM_TEMPLATES[RoomType.BUG_FIX].declared_agents

    def test_planner_present_in_code_review_roster(self) -> None:
        """planner in code_review declared_agents."""
        assert "planner" in ROOM_TEMPLATES[RoomType.CODE_REVIEW].declared_agents

    def test_planner_present_in_idea_validation_roster(self) -> None:
        """planner in idea_validation declared_agents."""
        assert "planner" in ROOM_TEMPLATES[RoomType.IDEA_VALIDATION].declared_agents

    # Activation: speak=True in each declared room type (via state_change triggers)
    def test_planner_speaks_on_diagnosed_in_bug_fix(self) -> None:
        """planner speaks on STATE_TRANSITION(diagnosed) in bug_fix."""
        agents = _room_agents(RoomType.BUG_FIX)
        assert "planner" in agents
        ev = _st_ev(new_state="diagnosed", prior_state="reproduced")
        assert _speaks(agents["planner"], ev) is True

    def test_planner_speaks_on_reviewing_in_code_review(self) -> None:
        """planner speaks on STATE_TRANSITION(reviewing) in code_review."""
        agents = _room_agents(RoomType.CODE_REVIEW)
        assert "planner" in agents
        ev = _st_ev(new_state="reviewing", prior_state="setup")
        assert _speaks(agents["planner"], ev) is True

    def test_planner_speaks_on_pitching_in_idea_validation(self) -> None:
        """planner speaks on STATE_TRANSITION(pitching) in idea_validation."""
        agents = _room_agents(RoomType.IDEA_VALIDATION)
        assert "planner" in agents
        ev = _st_ev(new_state="pitching", prior_state="setup")
        assert _speaks(agents["planner"], ev) is True

    # Absent from non-declared room types (present/missing partition)
    def test_planner_absent_from_research_roster(self) -> None:
        """planner NOT in research declared_agents (non-declared room)."""
        assert "planner" not in ROOM_TEMPLATES[RoomType.RESEARCH].declared_agents
        assert "planner" not in _room_agents(RoomType.RESEARCH)

    def test_planner_absent_from_free_chat_roster(self) -> None:
        """planner NOT in free_chat declared_agents (non-declared room)."""
        assert "planner" not in ROOM_TEMPLATES[RoomType.FREE_CHAT].declared_agents
        assert "planner" not in _room_agents(RoomType.FREE_CHAT)


# ---------------------------------------------------------------------------
# P3.7-content-3: verifier (bug_fix, code_review)
# ---------------------------------------------------------------------------


class TestVerifierAgent:
    """Discriminating tests for the verifier agent (P3.7-content-3)."""

    def setup_method(self) -> None:
        self.agent = _ALL_AGENTS["verifier"]

    # Schema validation
    def test_verifier_loaded_as_valid_agent(self) -> None:
        """verifier.yaml loads and is a valid Agent instance."""
        assert isinstance(self.agent, Agent)
        assert self.agent.id == "verifier"
        assert self.agent.role == "verifier"

    def test_verifier_applies_to_room_states_non_empty(self) -> None:
        """verifier.applies_to.room_states is non-empty."""
        assert len(self.agent.applies_to.room_states) >= 1

    # Present in declared room types
    def test_verifier_present_in_bug_fix_roster(self) -> None:
        """verifier in bug_fix declared_agents."""
        assert "verifier" in ROOM_TEMPLATES[RoomType.BUG_FIX].declared_agents

    def test_verifier_present_in_code_review_roster(self) -> None:
        """verifier in code_review declared_agents."""
        assert "verifier" in ROOM_TEMPLATES[RoomType.CODE_REVIEW].declared_agents

    # Activation: speak=True in each declared room type (via state_change triggers)
    def test_verifier_speaks_on_fix_proposed_in_bug_fix(self) -> None:
        """verifier speaks on STATE_TRANSITION(fix_proposed) in bug_fix."""
        agents = _room_agents(RoomType.BUG_FIX)
        assert "verifier" in agents
        ev = _st_ev(new_state="fix_proposed", prior_state="diagnosed")
        assert _speaks(agents["verifier"], ev) is True

    def test_verifier_speaks_on_approved_in_code_review(self) -> None:
        """verifier speaks on STATE_TRANSITION(approved) in code_review."""
        agents = _room_agents(RoomType.CODE_REVIEW)
        assert "verifier" in agents
        ev = _st_ev(new_state="approved", prior_state="changes_requested")
        assert _speaks(agents["verifier"], ev) is True

    # Absent from non-declared room types (present/missing partition)
    def test_verifier_absent_from_research_roster(self) -> None:
        """verifier NOT in research declared_agents (non-declared room)."""
        assert "verifier" not in ROOM_TEMPLATES[RoomType.RESEARCH].declared_agents
        assert "verifier" not in _room_agents(RoomType.RESEARCH)

    def test_verifier_absent_from_idea_validation_roster(self) -> None:
        """verifier NOT in idea_validation declared_agents (non-declared room)."""
        assert "verifier" not in ROOM_TEMPLATES[RoomType.IDEA_VALIDATION].declared_agents
        assert "verifier" not in _room_agents(RoomType.IDEA_VALIDATION)


# ---------------------------------------------------------------------------
# P3.7-content-4: mentor (free_chat, idea_validation)
# ---------------------------------------------------------------------------


class TestMentorAgent:
    """Discriminating tests for the mentor agent (P3.7-content-4)."""

    def setup_method(self) -> None:
        self.agent = _ALL_AGENTS["mentor"]

    # Schema validation
    def test_mentor_loaded_as_valid_agent(self) -> None:
        """mentor.yaml loads and is a valid Agent instance."""
        assert isinstance(self.agent, Agent)
        assert self.agent.id == "mentor"
        assert self.agent.role == "mentor"

    def test_mentor_applies_to_room_states_non_empty(self) -> None:
        """mentor.applies_to.room_states is non-empty."""
        assert len(self.agent.applies_to.room_states) >= 1

    # Present in declared room types
    def test_mentor_present_in_free_chat_roster(self) -> None:
        """mentor in free_chat declared_agents."""
        assert "mentor" in ROOM_TEMPLATES[RoomType.FREE_CHAT].declared_agents

    def test_mentor_present_in_idea_validation_roster(self) -> None:
        """mentor in idea_validation declared_agents."""
        assert "mentor" in ROOM_TEMPLATES[RoomType.IDEA_VALIDATION].declared_agents

    # Activation: speak=True in each declared room type on USER_INPUT event
    def test_mentor_speaks_on_user_input_in_free_chat(self) -> None:
        """mentor speaks on USER_INPUT event when loaded for free_chat."""
        agents = _room_agents(RoomType.FREE_CHAT)
        assert "mentor" in agents
        ev = _ev(EventType.USER_INPUT, content="can you explain this?")
        assert _speaks(agents["mentor"], ev) is True

    def test_mentor_speaks_on_user_input_in_idea_validation(self) -> None:
        """mentor speaks on USER_INPUT event when loaded for idea_validation."""
        agents = _room_agents(RoomType.IDEA_VALIDATION)
        assert "mentor" in agents
        ev = _ev(EventType.USER_INPUT, content="I am not sure I understand")
        assert _speaks(agents["mentor"], ev) is True

    # Absent from non-declared room types (present/missing partition)
    def test_mentor_absent_from_research_roster(self) -> None:
        """mentor NOT in research declared_agents (non-declared room)."""
        assert "mentor" not in ROOM_TEMPLATES[RoomType.RESEARCH].declared_agents
        assert "mentor" not in _room_agents(RoomType.RESEARCH)

    def test_mentor_absent_from_bug_fix_roster(self) -> None:
        """mentor NOT in bug_fix declared_agents (non-declared room)."""
        assert "mentor" not in ROOM_TEMPLATES[RoomType.BUG_FIX].declared_agents
        assert "mentor" not in _room_agents(RoomType.BUG_FIX)
