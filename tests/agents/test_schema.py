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
    AgentAppliesTo,
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
    ExternalValidationMeta,
    StateTransitionMeta,
    build_author,
    generate_event_id,
    generate_room_id,
    now_ms,
    validate_metadata,
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
    m = StateTransitionMeta(new_state="research", prior_state="setup")
    assert m.new_state == "research"
    assert m.prior_state == "setup"


def test_state_transition_meta_empty_new_state_raises() -> None:
    with pytest.raises(ValidationError):
        StateTransitionMeta(new_state="", prior_state="setup")


def test_state_transition_meta_frozen() -> None:
    m = StateTransitionMeta(new_state="research", prior_state="setup")
    with pytest.raises((ValidationError, TypeError)):
        m.new_state = "other"


def test_state_transition_meta_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        StateTransitionMeta(new_state="x", prior_state="y", unknown_field="z")  # type: ignore[call-arg]


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
# AgentMatchRecord — §6  (P1.5: applies_to_match + reason reintroduced)
# ===========================================================================


def test_agent_match_record_accepts_valid() -> None:
    r = AgentMatchRecord(
        agent_id="skeptic",
        loaded=True,
        applies_to_match=True,
        reason="room_type_match",
    )
    assert r.loaded is True
    assert r.applies_to_match is True
    assert r.reason == "room_type_match"


def test_agent_match_record_accepts_mismatch_reason() -> None:
    r = AgentMatchRecord(
        agent_id="skeptic",
        loaded=False,
        applies_to_match=False,
        reason="room_type_mismatch",
    )
    assert r.loaded is False
    assert r.reason == "room_type_mismatch"


def test_agent_match_record_invalid_reason_raises() -> None:
    with pytest.raises(ValidationError):
        AgentMatchRecord(
            agent_id="x",
            loaded=True,
            applies_to_match=True,
            reason="some_invalid_reason",  # type: ignore[arg-type]
        )


def test_agent_match_record_frozen() -> None:
    r = AgentMatchRecord(
        agent_id="x",
        loaded=True,
        applies_to_match=True,
        reason="room_type_match",
    )
    with pytest.raises((ValidationError, TypeError)):
        r.loaded = False


# ===========================================================================
# AgentSelectionTrace — §6
# ===========================================================================


def test_agent_selection_trace_accepts_valid() -> None:
    t = AgentSelectionTrace(
        considered=[
            AgentMatchRecord(
                agent_id="x",
                loaded=True,
                applies_to_match=True,
                reason="room_type_match",
            )
        ],
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
            considered=[
                AgentMatchRecord(
                    agent_id=_MIN_AGENT.id,
                    loaded=True,
                    applies_to_match=True,
                    reason="room_type_match",
                )
            ],
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


def test_agent_context_snapshot_excerpt_accepted() -> None:
    """P4.1: snapshot_excerpt is a first-class field on AgentContext (ADR-033 D2/D6)."""
    excerpt = "[tool_result] agent: hi"
    ctx = AgentContext(agent=_MIN_AGENT, skill_bodies=[], snapshot_excerpt=excerpt)
    assert ctx.snapshot_excerpt == excerpt


def test_agent_context_snapshot_excerpt_defaults_none() -> None:
    """snapshot_excerpt defaults to None when omitted."""
    ctx = AgentContext(agent=_MIN_AGENT, skill_bodies=[])
    assert ctx.snapshot_excerpt is None


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


# ===========================================================================
# StateTransitionMeta.prior_state extension (P1.5-3) — §5 + §6
# ===========================================================================


def test_state_transition_meta_prior_state_accepts_valid() -> None:
    m = StateTransitionMeta(new_state="exploration", prior_state="setup")
    assert m.prior_state == "setup"


def test_state_transition_meta_empty_prior_state_raises() -> None:
    with pytest.raises(ValidationError):
        StateTransitionMeta(new_state="exploration", prior_state="")


def test_state_transition_meta_missing_prior_state_raises() -> None:
    with pytest.raises(ValidationError):
        StateTransitionMeta(new_state="exploration")  # type: ignore[call-arg]


# ===========================================================================
# AgentAppliesTo (P1.5-3) — §5 + §6
# ===========================================================================


def test_agent_applies_to_accepts_star_wildcard() -> None:
    a = AgentAppliesTo(room_types=["*"], room_states=["*"])
    assert a.room_types == ["*"]
    assert a.room_states == ["*"]


def test_agent_applies_to_accepts_concrete_values() -> None:
    a = AgentAppliesTo(room_types=["research"], room_states=["exploration", "divergence"])
    assert a.room_types == ["research"]
    assert a.room_states == ["exploration", "divergence"]


def test_agent_applies_to_frozen() -> None:
    a = AgentAppliesTo(room_types=["*"], room_states=["*"])
    with pytest.raises((ValidationError, TypeError)):
        a.room_types = ["research"]


def test_agent_applies_to_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        AgentAppliesTo(room_types=["*"], room_states=["*"], extra_field="x")  # type: ignore[call-arg]


def test_agent_applies_to_empty_room_types_raises() -> None:
    with pytest.raises(ValidationError):
        AgentAppliesTo(room_types=[], room_states=["*"])


def test_agent_applies_to_empty_room_states_raises() -> None:
    with pytest.raises(ValidationError):
        AgentAppliesTo(room_types=["*"], room_states=[])


# §5 multi-position boundary tests — ["*"] sentinel must be exclusive


def test_agent_applies_to_star_leading_mixed_raises() -> None:
    """["*", "research"] — star at position 0, mixed with concrete value."""
    with pytest.raises(ValidationError, match=r"\*"):
        AgentAppliesTo(room_types=["*", "research"], room_states=["*"])


def test_agent_applies_to_star_trailing_mixed_raises() -> None:
    """["research", "*"] — star at last position, mixed with concrete value."""
    with pytest.raises(ValidationError, match=r"\*"):
        AgentAppliesTo(room_types=["research", "*"], room_states=["*"])


def test_agent_applies_to_star_middle_mixed_raises() -> None:
    """["free_chat", "*", "bug_fix"] — star in the middle."""
    with pytest.raises(ValidationError, match=r"\*"):
        AgentAppliesTo(room_types=["free_chat", "*", "bug_fix"], room_states=["*"])


# Agent.applies_to field — default + override


def test_agent_applies_to_default_is_wildcard() -> None:
    """Agent with no applies_to gets the all-rooms wildcard default."""
    a = Agent(id="x", role="r", persona="p", llm_config=_LLM)
    assert a.applies_to.room_types == ["*"]
    assert a.applies_to.room_states == ["*"]


def test_agent_applies_to_custom_override() -> None:
    """Agent can declare specific room-type + room-state filters."""
    a = Agent(
        id="x",
        role="r",
        persona="p",
        llm_config=_LLM,
        applies_to=AgentAppliesTo(room_types=["research"], room_states=["exploration"]),
    )
    assert a.applies_to.room_types == ["research"]
    assert a.applies_to.room_states == ["exploration"]


# ===========================================================================
# ExternalValidationMeta (core/event.py P2.3-2) — §4 exception payloads + §5 boundary validators
# ===========================================================================

_VALID_HYP_ID = "hyp_" + "a" * 32


def test_external_validation_meta_in_typed_metadata() -> None:
    assert TYPED_METADATA[EventType.EXTERNAL_VALIDATION] is ExternalValidationMeta


def test_external_validation_meta_accepts_valid_confirmed() -> None:
    m = ExternalValidationMeta(
        source="ci",
        verdict="confirmed",
        validated_hypothesis_id=_VALID_HYP_ID,
    )
    assert m.verdict == "confirmed"
    assert m.evidence_ref is None


def test_external_validation_meta_accepts_all_verdict_values() -> None:
    for v in ("confirmed", "refuted", "inconclusive"):
        m = ExternalValidationMeta(
            source="doi-resolver",
            verdict=v,
            validated_hypothesis_id=_VALID_HYP_ID,
        )
        assert m.verdict == v


def test_external_validation_meta_accepts_evidence_ref() -> None:
    m = ExternalValidationMeta(
        source="ci",
        verdict="confirmed",
        validated_hypothesis_id=_VALID_HYP_ID,
        evidence_ref="https://example.com/run/42",
    )
    assert m.evidence_ref == "https://example.com/run/42"


def test_external_validation_meta_missing_source_raises() -> None:
    with pytest.raises(ValidationError):
        ExternalValidationMeta(
            verdict="confirmed",
            validated_hypothesis_id=_VALID_HYP_ID,
        )  # type: ignore[call-arg]


def test_external_validation_meta_empty_source_raises() -> None:
    with pytest.raises(ValidationError):
        ExternalValidationMeta(
            source="", verdict="confirmed", validated_hypothesis_id=_VALID_HYP_ID
        )


def test_external_validation_meta_invalid_verdict_raises() -> None:
    with pytest.raises(ValidationError):
        ExternalValidationMeta(
            source="ci",
            verdict="unknown",  # type: ignore[arg-type]
            validated_hypothesis_id=_VALID_HYP_ID,
        )


def test_external_validation_meta_bad_hyp_id_pattern_raises() -> None:
    with pytest.raises(ValidationError):
        ExternalValidationMeta(
            source="ci",
            verdict="confirmed",
            validated_hypothesis_id="notahypid",
        )


def test_external_validation_meta_wrong_prefix_raises() -> None:
    with pytest.raises(ValidationError):
        ExternalValidationMeta(
            source="ci",
            verdict="confirmed",
            validated_hypothesis_id="vk_" + "a" * 32,  # vk_ prefix, not hyp_
        )


def test_external_validation_meta_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        ExternalValidationMeta(
            source="ci",
            verdict="confirmed",
            validated_hypothesis_id=_VALID_HYP_ID,
            unknown_field="x",  # type: ignore[call-arg]
        )


def test_external_validation_meta_frozen() -> None:
    m = ExternalValidationMeta(
        source="ci",
        verdict="confirmed",
        validated_hypothesis_id=_VALID_HYP_ID,
    )
    with pytest.raises((ValidationError, TypeError)):
        m.verdict = "refuted"


def test_validate_metadata_external_validation_wellformed() -> None:
    result = validate_metadata(
        EventType.EXTERNAL_VALIDATION,
        {
            "source": "ci",
            "verdict": "confirmed",
            "validated_hypothesis_id": _VALID_HYP_ID,
        },
    )
    assert result["verdict"] == "confirmed"
    assert result["evidence_ref"] is None


def test_validate_metadata_external_validation_missing_field_raises() -> None:
    from orchestrator.core.event import MetadataValidationError

    with pytest.raises(MetadataValidationError):
        validate_metadata(
            EventType.EXTERNAL_VALIDATION,
            {"source": "ci", "verdict": "confirmed"},  # missing validated_hypothesis_id
        )


def test_validate_metadata_external_validation_bad_verdict_raises() -> None:
    from orchestrator.core.event import MetadataValidationError

    with pytest.raises(MetadataValidationError):
        validate_metadata(
            EventType.EXTERNAL_VALIDATION,
            {"source": "ci", "verdict": "bad_value", "validated_hypothesis_id": _VALID_HYP_ID},
        )


def test_validate_metadata_external_validation_bad_hyp_id_raises() -> None:
    from orchestrator.core.event import MetadataValidationError

    with pytest.raises(MetadataValidationError):
        validate_metadata(
            EventType.EXTERNAL_VALIDATION,
            {"source": "ci", "verdict": "confirmed", "validated_hypothesis_id": "bad-id"},
        )
