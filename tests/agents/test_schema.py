"""§4/§5/§6 tests for agents schema + core/event.py P1.4-4 additions.

Covers:
  §4  exception payloads (AgentLoadError, SpeakingTriggerError, DispatchError)
  §5  boundary validators (cooldown_seconds, StateTransitionMeta.new_state)
  §6  schema invariants (frozen, extra-forbid, Field bounds, Literal)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.agents.exceptions import (
    AgentLoadError,
    DispatchError,
    SpeakingTriggerError,
)
from orchestrator.agents.schema import (
    Agent,
    AgentContext,
    AgentMatchRecord,
    AgentSelection,
    AgentSelectionTrace,
    EventTypeTrigger,
    RegexTrigger,
    SpeechDecision,
    StateChangeTrigger,
    TurnResult,
)
from orchestrator.core.event import (
    TYPED_METADATA,
    Event,
    EventType,
    StateTransitionMeta,
    build_author,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.llm.types import AgentAutonomyThresholds, AgentLLMConfig, ModelId

# ---------------------------------------------------------------------------
# Minimal fixtures
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
_MIN_AGENT = Agent(id="test-agent", role="r", persona="p", llm_config=_LLM)


def _make_event(**overrides: object) -> Event:
    defaults: dict[str, object] = dict(
        id=generate_event_id(),
        room_id=generate_room_id(),
        type=EventType.UTTERANCE,
        author="user",
        timestamp=now_ms(),
        content="hello",
    )
    defaults.update(overrides)
    return Event.model_validate(defaults)


# ===========================================================================
# StateTransitionMeta (core/event.py addition) — §5 + §6
# ===========================================================================


def test_state_transition_meta_accepts_valid() -> None:
    m = StateTransitionMeta(new_state="research")
    assert m.new_state == "research"


def test_state_transition_meta_empty_new_state_raises() -> None:
    with pytest.raises(ValidationError):
        StateTransitionMeta(new_state="")


def test_state_transition_meta_frozen() -> None:
    m = StateTransitionMeta(new_state="research")
    with pytest.raises((ValidationError, TypeError)):
        m.new_state = "other"


def test_state_transition_meta_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        StateTransitionMeta(new_state="x", unknown_field="y")  # type: ignore[call-arg]


def test_state_transition_meta_in_typed_metadata() -> None:
    assert TYPED_METADATA[EventType.STATE_TRANSITION] is StateTransitionMeta


# ===========================================================================
# build_author (core/event.py addition) — §4/§5
# ===========================================================================


def test_build_author_happy_path() -> None:
    assert build_author("skeptic") == "agent:skeptic"


def test_build_author_hyphen_and_digits() -> None:
    assert build_author("agent-001") == "agent:agent-001"


def test_build_author_empty_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_author("")


# ===========================================================================
# RegexTrigger — §6
# ===========================================================================


def test_regex_trigger_accepts_valid() -> None:
    t = RegexTrigger(pattern="hypothesis")
    assert t.type == "regex"
    assert t.pattern == "hypothesis"


def test_regex_trigger_empty_pattern_raises() -> None:
    with pytest.raises(ValidationError):
        RegexTrigger(pattern="")


def test_regex_trigger_frozen() -> None:
    t = RegexTrigger(pattern="x")
    with pytest.raises((ValidationError, TypeError)):
        t.pattern = "y"


def test_regex_trigger_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        RegexTrigger(pattern="x", extra="y")  # type: ignore[call-arg]


# ===========================================================================
# EventTypeTrigger — §6
# ===========================================================================


def test_event_type_trigger_accepts_valid() -> None:
    t = EventTypeTrigger(event_type=EventType.HYPOTHESIS)
    assert t.event_type == EventType.HYPOTHESIS


def test_event_type_trigger_invalid_event_type_raises() -> None:
    with pytest.raises(ValidationError):
        EventTypeTrigger(event_type="not_a_type")  # type: ignore[arg-type]


def test_event_type_trigger_frozen() -> None:
    t = EventTypeTrigger(event_type=EventType.UTTERANCE)
    with pytest.raises((ValidationError, TypeError)):
        t.event_type = EventType.DECISION


# ===========================================================================
# StateChangeTrigger — §6
# ===========================================================================


def test_state_change_trigger_accepts_valid() -> None:
    t = StateChangeTrigger(target_state="research")
    assert t.target_state == "research"


def test_state_change_trigger_empty_target_raises() -> None:
    with pytest.raises(ValidationError):
        StateChangeTrigger(target_state="")


def test_state_change_trigger_frozen() -> None:
    t = StateChangeTrigger(target_state="x")
    with pytest.raises((ValidationError, TypeError)):
        t.target_state = "y"


# ===========================================================================
# Agent — §5 + §6
# ===========================================================================


def test_agent_accepts_minimal() -> None:
    assert _MIN_AGENT.id == "test-agent"
    assert _MIN_AGENT.cooldown_seconds == 0


def test_agent_empty_id_raises() -> None:
    with pytest.raises(ValidationError):
        Agent(id="", role="r", persona="p", llm_config=_LLM)


def test_agent_negative_cooldown_raises() -> None:
    with pytest.raises(ValidationError):
        Agent(id="x", role="r", persona="p", llm_config=_LLM, cooldown_seconds=-1)


def test_agent_zero_cooldown_ok() -> None:
    a = Agent(id="x", role="r", persona="p", llm_config=_LLM, cooldown_seconds=0)
    assert a.cooldown_seconds == 0


def test_agent_positive_cooldown_ok() -> None:
    a = Agent(id="x", role="r", persona="p", llm_config=_LLM, cooldown_seconds=60)
    assert a.cooldown_seconds == 60


def test_agent_frozen() -> None:
    with pytest.raises((ValidationError, TypeError)):
        _MIN_AGENT.id = "other"


def test_agent_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        Agent(  # type: ignore[call-arg]
            id="x",
            role="r",
            persona="p",
            llm_config=_LLM,
            priority=50,
        )


def test_agent_accepts_all_trigger_types() -> None:
    a = Agent(
        id="multi",
        role="r",
        persona="p",
        llm_config=_LLM,
        speaking_triggers=[
            RegexTrigger(pattern="hello"),
            EventTypeTrigger(event_type=EventType.HYPOTHESIS),
            StateChangeTrigger(target_state="research"),
        ],
    )
    assert len(a.speaking_triggers) == 3


# ===========================================================================
# SpeechDecision — §6
# ===========================================================================


def test_speech_decision_accepts_valid() -> None:
    d = SpeechDecision(
        agent_id="skeptic",
        speak=True,
        reason="trigger_matched",
        matched_trigger_index=0,
    )
    assert d.speak is True


def test_speech_decision_invalid_reason_raises() -> None:
    with pytest.raises(ValidationError):
        SpeechDecision(agent_id="x", speak=False, reason="bad_reason")  # type: ignore[arg-type]


def test_speech_decision_frozen() -> None:
    d = SpeechDecision(agent_id="x", speak=False, reason="no_triggers_configured")
    with pytest.raises((ValidationError, TypeError)):
        d.speak = True


def test_speech_decision_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        SpeechDecision(  # type: ignore[call-arg]
            agent_id="x",
            speak=False,
            reason="no_triggers_configured",
            unknown="y",
        )


# ===========================================================================
# AgentMatchRecord — §6  (regression: no `reason` field per R0-A Y1)
# ===========================================================================


def test_agent_match_record_accepts_valid() -> None:
    r = AgentMatchRecord(agent_id="skeptic", loaded=True)
    assert r.loaded is True


def test_agent_match_record_extra_forbid_rejects_reason() -> None:
    with pytest.raises(ValidationError):
        AgentMatchRecord(agent_id="x", loaded=True, reason="some_reason")  # type: ignore[call-arg]


def test_agent_match_record_frozen() -> None:
    r = AgentMatchRecord(agent_id="x", loaded=True)
    with pytest.raises((ValidationError, TypeError)):
        r.loaded = False


# ===========================================================================
# AgentSelectionTrace — §6
# ===========================================================================


def test_agent_selection_trace_accepts_valid() -> None:
    t = AgentSelectionTrace(
        considered=[AgentMatchRecord(agent_id="x", loaded=True)],
        loaded_count=1,
    )
    assert t.loaded_count == 1


def test_agent_selection_trace_negative_count_raises() -> None:
    with pytest.raises(ValidationError):
        AgentSelectionTrace(considered=[], loaded_count=-1)


def test_agent_selection_trace_frozen() -> None:
    t = AgentSelectionTrace(considered=[], loaded_count=0)
    with pytest.raises((ValidationError, TypeError)):
        t.loaded_count = 5


# ===========================================================================
# AgentSelection — §6
# ===========================================================================


def test_agent_selection_accepts_valid() -> None:
    sel = AgentSelection(
        loaded=[_MIN_AGENT],
        trace=AgentSelectionTrace(
            considered=[AgentMatchRecord(agent_id=_MIN_AGENT.id, loaded=True)],
            loaded_count=1,
        ),
    )
    assert len(sel.loaded) == 1


def test_agent_selection_frozen() -> None:
    sel = AgentSelection(
        loaded=[],
        trace=AgentSelectionTrace(considered=[], loaded_count=0),
    )
    with pytest.raises((ValidationError, TypeError)):
        sel.loaded = [_MIN_AGENT]


# ===========================================================================
# AgentContext — §6
# ===========================================================================


def test_agent_context_accepts_valid() -> None:
    ctx = AgentContext(agent=_MIN_AGENT, skill_bodies=["body1", "body2"])
    assert ctx.skill_bodies == ["body1", "body2"]


def test_agent_context_frozen() -> None:
    ctx = AgentContext(agent=_MIN_AGENT, skill_bodies=[])
    with pytest.raises((ValidationError, TypeError)):
        ctx.skill_bodies = ["x"]


def test_agent_context_extra_forbid_rejects_snapshot_excerpt() -> None:
    with pytest.raises(ValidationError):
        AgentContext(  # type: ignore[call-arg]
            agent=_MIN_AGENT,
            skill_bodies=[],
            snapshot_excerpt="...",
        )


# ===========================================================================
# TurnResult — §5 + §6
# ===========================================================================


def test_turn_result_nothing_to_say_case() -> None:
    r = TurnResult(utterances=[], failed_agents=[], total_asked=0)
    assert r.total_asked == 0
    assert r.utterances == []
    assert r.failed_agents == []


def test_turn_result_success_case() -> None:
    ev = _make_event()
    r = TurnResult(utterances=[ev], failed_agents=[], total_asked=1)
    assert r.total_asked == 1
    assert len(r.utterances) == 1


def test_turn_result_all_fail_case() -> None:
    r = TurnResult(utterances=[], failed_agents=["skeptic", "prober"], total_asked=2)
    assert r.total_asked == 2
    assert r.failed_agents == ["skeptic", "prober"]
    assert r.utterances == []


def test_turn_result_negative_total_asked_raises() -> None:
    with pytest.raises(ValidationError):
        TurnResult(utterances=[], total_asked=-1)


def test_turn_result_frozen() -> None:
    r = TurnResult(utterances=[], total_asked=0)
    with pytest.raises((ValidationError, TypeError)):
        r.total_asked = 1


def test_turn_result_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        TurnResult(utterances=[], total_asked=0, unexpected="x")  # type: ignore[call-arg]


# ===========================================================================
# §4 exception payloads
# ===========================================================================


def test_agent_load_error_carries_agent_id_and_field() -> None:
    exc = AgentLoadError("bad file", agent_id="skeptic", field="id")
    assert exc.agent_id == "skeptic"
    assert exc.field == "id"
    assert "bad file" in str(exc)


def test_agent_load_error_defaults_none() -> None:
    exc = AgentLoadError("oops")
    assert exc.agent_id is None
    assert exc.field is None


def test_speaking_trigger_error_carries_agent_id_and_index() -> None:
    exc = SpeakingTriggerError("bad regex", agent_id="prober", trigger_index=2)
    assert exc.agent_id == "prober"
    assert exc.trigger_index == 2
    assert "bad regex" in str(exc)


def test_speaking_trigger_error_defaults_none() -> None:
    exc = SpeakingTriggerError("oops")
    assert exc.agent_id is None
    assert exc.trigger_index is None


def test_dispatch_error_carries_agent_id() -> None:
    exc = DispatchError("dispatch failed", agent_id="skeptic")
    assert exc.agent_id == "skeptic"
    assert "dispatch failed" in str(exc)


def test_dispatch_error_defaults_none() -> None:
    exc = DispatchError("oops")
    assert exc.agent_id is None
