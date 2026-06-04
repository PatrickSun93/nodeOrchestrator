"""E2e + roster + net-activation tests for scaffold RoomTypes (P3.1).

Plan §3 atomics:
- §P3.1-2(a): load_room per room returns discriminating present/missing partition.
- §P3.1-2(b): should_agent_speak exact net activation per transition (existing
  event_type/regex triggers PLUS state_change triggers, per §2b-net table).
- §P3.1-2(c): facilitator loads + activates in free_chat; absent from
  analytical rooms.
- §P3.1-2(e): facilitator.yaml validates against the frozen Agent schema
  (ADR-024 D1).

Design notes:
- Content for triggering events is chosen to avoid the regex triggers
  (prober: "?"; skeptic: "assume/given that/we know/obviously/clearly") so
  that only *structural* (event_type / state_change) triggers fire.
  Content-dependent firings are explicitly out of scope for this test file
  (they are opportunistic, not structural).
- All should_agent_speak calls pass an empty event_stream_snapshot so
  cooldown never blocks — cooldown is tested in test_should_agent_speak.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
from orchestrator.rooms.templates import ROOM_TEMPLATES, load_room

# ---------------------------------------------------------------------------
# Module-level agent loading (loaded once; read-only)
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

# Convenience: expected roster per scaffold room_type (room_type-filtered set)
_ROOM_ROSTER: dict[RoomType, frozenset[str]] = {
    RoomType.BUG_FIX: frozenset({"logger", "operator", "planner", "prober", "skeptic", "verifier"}),
    RoomType.CODE_REVIEW: frozenset(
        {"logger", "operator", "planner", "skeptic", "synthesizer", "verifier"}
    ),
    RoomType.IDEA_VALIDATION: frozenset(
        {
            "divergence_mapper",
            "logger",
            "mentor",
            "operator",
            "planner",
            "prober",
            "skeptic",
            "synthesizer",
        }
    ),
    RoomType.FREE_CHAT: frozenset({"facilitator", "logger", "mentor"}),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROOM_ID = generate_room_id()


def _room_agents(room_type: RoomType) -> dict[str, Agent]:
    """Agents that decide_agents_for_room loads for room_type (applies_to filter)."""
    sel = decide_agents_for_room(room_type, "setup", available_agents=_ALL_AGENTS)
    return {a.id: a for a in sel.loaded}


def _speaking_ids(agents: dict[str, Agent], current_event: Event) -> frozenset[str]:
    """Agent IDs that speak on current_event (empty snapshot → no cooldown)."""
    return frozenset(
        aid
        for aid, agent in agents.items()
        if should_agent_speak(
            agent, [], current_event=current_event, regex_registry=_REGEX_REGISTRY
        ).speak
    )


def _ev(event_type: EventType, *, content: str = "safe content") -> Event:
    """Construct a minimal non-STATE_TRANSITION event."""
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
    """Construct a STATE_TRANSITION event with typed metadata."""
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


# ---------------------------------------------------------------------------
# §P3.1-2(a): load_room discriminating per-room roster tests
# ---------------------------------------------------------------------------


class TestLoadRoomDiscriminating:
    """load_room returns the correct present/missing partition per scaffold room."""

    @pytest.mark.parametrize("room_type", list(_ROOM_ROSTER))
    def test_all_declared_agents_present_when_loaded_from_config(self, room_type: RoomType) -> None:
        """load_room with all config agents available: missing == []."""
        _, missing = load_room(room_type, _ALL_AGENTS)
        assert missing == [], f"{room_type.value}: unexpected missing={missing}"

    @pytest.mark.parametrize("room_type", list(_ROOM_ROSTER))
    def test_declared_agents_match_plan_roster(self, room_type: RoomType) -> None:
        """ROOM_TEMPLATES declared_agents matches the plan §2a roster."""
        declared = frozenset(ROOM_TEMPLATES[room_type].declared_agents)
        assert declared == _ROOM_ROSTER[room_type], (
            f"{room_type.value}: declared={declared} != expected={_ROOM_ROSTER[room_type]}"
        )

    def test_free_chat_declares_facilitator_bug_fix_does_not(self) -> None:
        """FREE_CHAT declares facilitator; BUG_FIX does not (per-room discriminating)."""
        fc = frozenset(ROOM_TEMPLATES[RoomType.FREE_CHAT].declared_agents)
        bf = frozenset(ROOM_TEMPLATES[RoomType.BUG_FIX].declared_agents)
        assert "facilitator" in fc
        assert "facilitator" not in bf

    def test_idea_validation_declares_divergence_mapper_code_review_does_not(self) -> None:
        """IDEA_VALIDATION declares divergence_mapper; CODE_REVIEW does not."""
        iv = frozenset(ROOM_TEMPLATES[RoomType.IDEA_VALIDATION].declared_agents)
        cr = frozenset(ROOM_TEMPLATES[RoomType.CODE_REVIEW].declared_agents)
        assert "divergence_mapper" in iv
        assert "divergence_mapper" not in cr

    def test_bug_fix_declares_prober_code_review_does_not(self) -> None:
        """BUG_FIX declares prober; CODE_REVIEW does not."""
        bf = frozenset(ROOM_TEMPLATES[RoomType.BUG_FIX].declared_agents)
        cr = frozenset(ROOM_TEMPLATES[RoomType.CODE_REVIEW].declared_agents)
        assert "prober" in bf
        assert "prober" not in cr

    @pytest.mark.parametrize("room_type", list(_ROOM_ROSTER))
    def test_decide_agents_for_room_matches_declared_roster(self, room_type: RoomType) -> None:
        """decide_agents_for_room(room_type) returns exactly the plan §2a roster."""
        loaded_ids = frozenset(_room_agents(room_type).keys())
        assert loaded_ids == _ROOM_ROSTER[room_type], (
            f"{room_type.value}: loaded={loaded_ids} != expected={_ROOM_ROSTER[room_type]}"
        )


# ---------------------------------------------------------------------------
# §P3.1-2(b): net activation per transition — bug_fix
# ---------------------------------------------------------------------------


class TestBugFixActivation:
    """Per-transition net activation for BUG_FIX.

    Per §2b-net:
      setup→reproduced   (OBSERVATION):    trigger={};    state_change={prober}
      reproduced→diagnosed (HYPOTHESIS):   trigger={skeptic,operator};  state_change={skeptic}
      diagnosed→fix_proposed (DECISION):   trigger={};    state_change={skeptic,operator}
      fix_proposed→closed (SUMMARY_SNAPSHOT): trigger={}; state_change={}
    """

    def setup_method(self) -> None:
        self.agents = _room_agents(RoomType.BUG_FIX)

    # setup → reproduced
    def test_observation_event_fires_no_existing_trigger(self) -> None:
        """OBSERVATION fires no event_type/regex trigger in bug_fix."""
        ev = _ev(EventType.OBSERVATION, content="bug observed in system")
        assert _speaking_ids(self.agents, ev) == frozenset()

    def test_state_transition_reproduced_fires_prober(self) -> None:
        """STATE_TRANSITION(reproduced) fires prober via state_change→reproduced."""
        ev = _st_ev(new_state="reproduced", prior_state="setup")
        assert _speaking_ids(self.agents, ev) == frozenset({"prober"})

    # reproduced → diagnosed
    def test_hypothesis_event_fires_skeptic_and_operator(self) -> None:
        """HYPOTHESIS fires skeptic (event_type) + operator (event_type) in bug_fix."""
        ev = _ev(EventType.HYPOTHESIS, content="root cause is lock contention")
        assert _speaking_ids(self.agents, ev) == frozenset({"skeptic", "operator"})

    def test_state_transition_diagnosed_fires_skeptic_and_planner(self) -> None:
        """STATE_TRANSITION(diagnosed) fires skeptic + planner via state_change→diagnosed."""
        ev = _st_ev(new_state="diagnosed", prior_state="reproduced")
        assert _speaking_ids(self.agents, ev) == frozenset({"skeptic", "planner"})

    # diagnosed → fix_proposed
    def test_decision_event_fires_no_existing_trigger(self) -> None:
        """DECISION fires no event_type/regex trigger in bug_fix (RC-25 control)."""
        ev = _ev(EventType.DECISION, content="fix approach determined")
        assert _speaking_ids(self.agents, ev) == frozenset()

    def test_state_transition_fix_proposed_fires_skeptic_operator_verifier(self) -> None:
        """STATE_TRANSITION(fix_proposed) fires skeptic + operator + verifier via state_change."""
        ev = _st_ev(new_state="fix_proposed", prior_state="diagnosed")
        assert _speaking_ids(self.agents, ev) == frozenset({"skeptic", "operator", "verifier"})

    # fix_proposed → closed
    def test_summary_snapshot_fires_no_existing_trigger(self) -> None:
        """SUMMARY_SNAPSHOT fires no event_type/regex trigger in bug_fix (RC-25 control)."""
        ev = _ev(EventType.SUMMARY_SNAPSHOT, content="summary complete")
        assert _speaking_ids(self.agents, ev) == frozenset()

    def test_state_transition_closed_fires_no_agent(self) -> None:
        """STATE_TRANSITION(closed) fires no agent in bug_fix (logger deferred P3.7)."""
        ev = _st_ev(new_state="closed", prior_state="fix_proposed")
        assert _speaking_ids(self.agents, ev) == frozenset()


# ---------------------------------------------------------------------------
# §P3.1-2(b): net activation per transition — code_review
# ---------------------------------------------------------------------------


class TestCodeReviewActivation:
    """Per-transition net activation for CODE_REVIEW.

    Per §2b-net:
      setup→reviewing      (OBSERVATION): trigger={};    state_change={skeptic,operator}
      reviewing→changes_requested (REJECTION): trigger={}; state_change={skeptic}
      changes_requested→approved (DECISION): trigger={}; state_change={}
      approved→closed   (SUMMARY_SNAPSHOT): trigger={}; state_change={}
    """

    def setup_method(self) -> None:
        self.agents = _room_agents(RoomType.CODE_REVIEW)

    # setup → reviewing
    def test_observation_fires_no_existing_trigger(self) -> None:
        """OBSERVATION fires no event_type/regex trigger in code_review."""
        ev = _ev(EventType.OBSERVATION, content="code change observed")
        assert _speaking_ids(self.agents, ev) == frozenset()

    def test_state_transition_reviewing_fires_skeptic_operator_planner(self) -> None:
        """STATE_TRANSITION(reviewing) fires skeptic + operator + planner via state_change."""
        ev = _st_ev(new_state="reviewing", prior_state="setup")
        assert _speaking_ids(self.agents, ev) == frozenset({"skeptic", "operator", "planner"})

    # reviewing → changes_requested
    def test_rejection_fires_no_existing_trigger(self) -> None:
        """REJECTION fires no event_type/regex trigger in code_review (RC-25 control)."""
        ev = _ev(EventType.REJECTION, content="changes needed here")
        assert _speaking_ids(self.agents, ev) == frozenset()

    def test_state_transition_changes_requested_fires_skeptic_only(self) -> None:
        """STATE_TRANSITION(changes_requested) fires skeptic via state_change."""
        ev = _st_ev(new_state="changes_requested", prior_state="reviewing")
        assert _speaking_ids(self.agents, ev) == frozenset({"skeptic"})

    # changes_requested → approved
    def test_decision_fires_synthesizer(self) -> None:
        """DECISION fires synthesizer (event_type trigger) in code_review."""
        ev = _ev(EventType.DECISION, content="approved for merge")
        assert _speaking_ids(self.agents, ev) == frozenset({"synthesizer"})

    def test_state_transition_approved_fires_verifier(self) -> None:
        """STATE_TRANSITION(approved) fires verifier in code_review."""
        ev = _st_ev(new_state="approved", prior_state="changes_requested")
        assert _speaking_ids(self.agents, ev) == frozenset({"verifier"})

    # approved → closed
    def test_summary_snapshot_fires_no_existing_trigger(self) -> None:
        """SUMMARY_SNAPSHOT fires no event_type/regex trigger in code_review."""
        ev = _ev(EventType.SUMMARY_SNAPSHOT, content="review summary done")
        assert _speaking_ids(self.agents, ev) == frozenset()

    def test_state_transition_closed_fires_no_agent(self) -> None:
        """STATE_TRANSITION(closed) fires no agent in code_review."""
        ev = _st_ev(new_state="closed", prior_state="approved")
        assert _speaking_ids(self.agents, ev) == frozenset()


# ---------------------------------------------------------------------------
# §P3.1-2(b): net activation per transition — idea_validation
# ---------------------------------------------------------------------------


class TestIdeaValidationActivation:
    """Per-transition net activation for IDEA_VALIDATION.

    Per §2b-net:
      setup→pitching      (UTTERANCE):  trigger={};               state_change={prober}
      pitching→validating (HYPOTHESIS): trigger={skeptic,operator};
          state_change={skeptic,divergence_mapper,operator}
      validating→decided  (DECISION):   trigger={};               state_change={}
      decided→closed   (SUMMARY_SNAPSHOT): trigger={};            state_change={}
    """

    def setup_method(self) -> None:
        self.agents = _room_agents(RoomType.IDEA_VALIDATION)

    # setup → pitching
    def test_utterance_fires_no_existing_trigger(self) -> None:
        """UTTERANCE fires no event_type/regex trigger in idea_validation.

        No agent in idea_validation has an event_type:utterance trigger.
        """
        ev = _ev(EventType.UTTERANCE, content="here is my idea")
        assert _speaking_ids(self.agents, ev) == frozenset()

    def test_state_transition_pitching_fires_prober_and_planner(self) -> None:
        """STATE_TRANSITION(pitching) fires prober + planner via state_change→pitching."""
        ev = _st_ev(new_state="pitching", prior_state="setup")
        assert _speaking_ids(self.agents, ev) == frozenset({"prober", "planner"})

    # pitching → validating (Y1 net: operator co-fires via existing hypothesis trigger)
    def test_hypothesis_fires_skeptic_and_operator(self) -> None:
        """HYPOTHESIS fires skeptic + operator via existing event_type hypothesis triggers."""
        ev = _ev(EventType.HYPOTHESIS, content="the idea is viable")
        assert _speaking_ids(self.agents, ev) == frozenset({"skeptic", "operator"})

    def test_state_transition_validating_fires_skeptic_divergence_mapper_operator(
        self,
    ) -> None:
        """STATE_TRANSITION(validating) fires skeptic + divergence_mapper + operator."""
        ev = _st_ev(new_state="validating", prior_state="pitching")
        assert _speaking_ids(self.agents, ev) == frozenset(
            {"skeptic", "divergence_mapper", "operator"}
        )

    # validating → decided
    def test_decision_fires_synthesizer(self) -> None:
        """DECISION fires synthesizer (event_type trigger) in idea_validation."""
        ev = _ev(EventType.DECISION, content="decision reached")
        assert _speaking_ids(self.agents, ev) == frozenset({"synthesizer"})

    def test_state_transition_decided_fires_no_agent(self) -> None:
        """STATE_TRANSITION(decided) fires no agent in idea_validation."""
        ev = _st_ev(new_state="decided", prior_state="validating")
        assert _speaking_ids(self.agents, ev) == frozenset()

    # decided → closed
    def test_summary_snapshot_fires_no_existing_trigger(self) -> None:
        """SUMMARY_SNAPSHOT fires no event_type/regex trigger in idea_validation."""
        ev = _ev(EventType.SUMMARY_SNAPSHOT, content="idea validated and decided")
        assert _speaking_ids(self.agents, ev) == frozenset()

    def test_state_transition_closed_fires_no_agent(self) -> None:
        """STATE_TRANSITION(closed) fires no agent in idea_validation."""
        ev = _st_ev(new_state="closed", prior_state="decided")
        assert _speaking_ids(self.agents, ev) == frozenset()


# ---------------------------------------------------------------------------
# §P3.1-2(b): net activation per transition — free_chat
# ---------------------------------------------------------------------------


class TestFreeChatActivation:
    """Per-transition net activation for FREE_CHAT.

    Per §2b-net:
      setup→active  (UTTERANCE):        trigger={};       state_change={facilitator}
      active→closed (SUMMARY_SNAPSHOT): trigger={};       state_change={}
    """

    def setup_method(self) -> None:
        self.agents = _room_agents(RoomType.FREE_CHAT)

    # setup → active
    def test_utterance_fires_no_existing_trigger_in_free_chat(self) -> None:
        """UTTERANCE fires no event_type/regex trigger in free_chat.

        facilitator has event_type:user_input (not utterance); logger has
        state_change→snapshot_pending only.
        """
        ev = _ev(EventType.UTTERANCE, content="starting conversation")
        assert _speaking_ids(self.agents, ev) == frozenset()

    def test_state_transition_active_fires_facilitator(self) -> None:
        """STATE_TRANSITION(active) fires facilitator via state_change→active."""
        ev = _st_ev(new_state="active", prior_state="setup")
        assert _speaking_ids(self.agents, ev) == frozenset({"facilitator"})

    # active → closed
    def test_summary_snapshot_fires_no_existing_trigger(self) -> None:
        """SUMMARY_SNAPSHOT fires no event_type/regex trigger in free_chat."""
        ev = _ev(EventType.SUMMARY_SNAPSHOT, content="chat concluded")
        assert _speaking_ids(self.agents, ev) == frozenset()

    def test_state_transition_closed_fires_no_agent(self) -> None:
        """STATE_TRANSITION(closed) fires no agent in free_chat."""
        ev = _st_ev(new_state="closed", prior_state="active")
        assert _speaking_ids(self.agents, ev) == frozenset()


# ---------------------------------------------------------------------------
# §P3.1-2(c): facilitator — activation in free_chat + absent from analytical
# ---------------------------------------------------------------------------


class TestFacilitatorActivation:
    """Facilitator activation tests (ADR-024 D2/D3)."""

    def setup_method(self) -> None:
        self.facilitator = _ALL_AGENTS["facilitator"]

    def test_facilitator_present_in_free_chat_roster(self) -> None:
        """facilitator is loaded by decide_agents_for_room for FREE_CHAT."""
        agents = _room_agents(RoomType.FREE_CHAT)
        assert "facilitator" in agents

    def test_facilitator_absent_from_bug_fix(self) -> None:
        """facilitator is NOT loaded for BUG_FIX (applies_to.room_types=[free_chat])."""
        agents = _room_agents(RoomType.BUG_FIX)
        assert "facilitator" not in agents

    def test_facilitator_absent_from_code_review(self) -> None:
        """facilitator is NOT loaded for CODE_REVIEW."""
        agents = _room_agents(RoomType.CODE_REVIEW)
        assert "facilitator" not in agents

    def test_facilitator_absent_from_idea_validation(self) -> None:
        """facilitator is NOT loaded for IDEA_VALIDATION."""
        agents = _room_agents(RoomType.IDEA_VALIDATION)
        assert "facilitator" not in agents

    def test_facilitator_absent_from_research(self) -> None:
        """facilitator is NOT loaded for RESEARCH."""
        agents = _room_agents(RoomType.RESEARCH)
        assert "facilitator" not in agents

    def test_facilitator_speaks_on_user_input(self) -> None:
        """facilitator speaks on USER_INPUT event (event_type trigger)."""
        ev = _ev(EventType.USER_INPUT, content="hello there")
        dec = should_agent_speak(
            self.facilitator, [], current_event=ev, regex_registry=_REGEX_REGISTRY
        )
        assert dec.speak is True

    def test_facilitator_speaks_on_state_change_active(self) -> None:
        """facilitator speaks on STATE_TRANSITION(active) (state_change trigger)."""
        ev = _st_ev(new_state="active", prior_state="setup")
        dec = should_agent_speak(
            self.facilitator, [], current_event=ev, regex_registry=_REGEX_REGISTRY
        )
        assert dec.speak is True

    def test_facilitator_silent_on_utterance(self) -> None:
        """facilitator does NOT speak on UTTERANCE (no utterance trigger)."""
        ev = _ev(EventType.UTTERANCE, content="some chat")
        dec = should_agent_speak(
            self.facilitator, [], current_event=ev, regex_registry=_REGEX_REGISTRY
        )
        assert dec.speak is False

    def test_facilitator_silent_on_state_change_other_room_state(self) -> None:
        """facilitator does NOT speak on STATE_TRANSITION(reproduced) — not its trigger."""
        ev = _st_ev(new_state="reproduced", prior_state="setup")
        dec = should_agent_speak(
            self.facilitator, [], current_event=ev, regex_registry=_REGEX_REGISTRY
        )
        assert dec.speak is False

    def test_facilitator_applies_to_room_types_is_free_chat_only(self) -> None:
        """facilitator.applies_to.room_types == ['free_chat'] (ADR-024 D3)."""
        assert self.facilitator.applies_to.room_types == ["free_chat"]

    def test_facilitator_applies_to_room_states_is_setup_and_active(self) -> None:
        """facilitator.applies_to.room_states == ['setup', 'active'] (ADR-024 D3)."""
        assert self.facilitator.applies_to.room_states == ["setup", "active"]


# ---------------------------------------------------------------------------
# §P3.1-2(e): facilitator.yaml validates against Agent schema (ADR-024 D1)
# ---------------------------------------------------------------------------


def test_facilitator_loaded_as_valid_agent() -> None:
    """facilitator.yaml loads without error and is an Agent instance."""
    assert "facilitator" in _ALL_AGENTS
    agent = _ALL_AGENTS["facilitator"]
    assert isinstance(agent, Agent)
    assert agent.id == "facilitator"
    assert agent.role == "facilitator"
    assert len(agent.persona) > 0
    assert len(agent.forbidden_behaviors) > 0


def test_facilitator_has_correct_triggers() -> None:
    """facilitator has exactly two triggers: event_type:user_input + state_change:active."""
    agent = _ALL_AGENTS["facilitator"]
    assert len(agent.speaking_triggers) == 2

    from orchestrator.agents.schema import EventTypeTrigger, StateChangeTrigger

    triggers_by_type = {type(t).__name__: t for t in agent.speaking_triggers}
    assert "EventTypeTrigger" in triggers_by_type
    assert "StateChangeTrigger" in triggers_by_type

    et = triggers_by_type["EventTypeTrigger"]
    assert isinstance(et, EventTypeTrigger)
    assert et.event_type == EventType.USER_INPUT

    sc = triggers_by_type["StateChangeTrigger"]
    assert isinstance(sc, StateChangeTrigger)
    assert sc.target_state == "active"


def test_facilitator_no_dissent_dimensions() -> None:
    """facilitator has no dissent_dimensions — it is a non-adversarial host (ADR-024 D1)."""
    agent = _ALL_AGENTS["facilitator"]
    assert agent.dissent_dimensions == []


def test_facilitator_llm_config_cheap_warm() -> None:
    """facilitator uses haiku model + 0.7 temperature (ADR-024 D4)."""
    agent = _ALL_AGENTS["facilitator"]
    assert agent.llm_config.default_model == ModelId("claude_code_haiku_45")
    assert agent.llm_config.temperature == 0.7


# ---------------------------------------------------------------------------
# Cross-room: Research roster unchanged (backward-compat verification)
# ---------------------------------------------------------------------------


def test_research_roster_after_p3_7_content() -> None:
    """Research loads 6 agents after P3.7-content (synthesizer added)."""
    research_agents = _room_agents(RoomType.RESEARCH)
    assert frozenset(research_agents.keys()) == frozenset(
        {"divergence_mapper", "logger", "operator", "prober", "skeptic", "synthesizer"}
    )
    assert "facilitator" not in research_agents


def test_prober_still_in_research_after_room_types_narrowed() -> None:
    """prober's room_types narrowing to [research, bug_fix, idea_validation] keeps it in Research."""  # noqa: E501
    prober = _ALL_AGENTS["prober"]
    assert "research" in prober.applies_to.room_types
    research_agents = _room_agents(RoomType.RESEARCH)
    assert "prober" in research_agents


def test_skeptic_still_in_research_after_room_types_narrowed() -> None:
    """skeptic's room_types narrowing keeps it in Research."""
    skeptic = _ALL_AGENTS["skeptic"]
    assert "research" in skeptic.applies_to.room_types
    research_agents = _room_agents(RoomType.RESEARCH)
    assert "skeptic" in research_agents
