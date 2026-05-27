"""Dedicated test file for should_agent_speak (per plan P1.4-7 + brief push-back #7).

All tests are table-driven where possible (parametrize).  Key regression:
cooldown unit conversion — cooldown_seconds is seconds; timestamps are ms.
"""

from __future__ import annotations

import re
from typing import Any, cast

import pytest

from orchestrator.agents.exceptions import SpeakingTriggerError
from orchestrator.agents.schema import (
    Agent,
    EventTypeTrigger,
    RegexTrigger,
    StateChangeTrigger,
)
from orchestrator.agents.speaking import should_agent_speak
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    TimestampMs,
    generate_event_id,
    generate_room_id,
)
from orchestrator.llm.types import AgentAutonomyThresholds, AgentLLMConfig, ModelId

# ---------------------------------------------------------------------------
# Helpers
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
_ROOM = generate_room_id()
_BASE_TS = TimestampMs(1_000_000)  # 1000s epoch; convenient ms anchor


def _make_event(
    *,
    type: EventType = EventType.USER_INPUT,
    content: str = "hello",
    author: str = "user",
    timestamp: TimestampMs = _BASE_TS,
    room_id: RoomId = _ROOM,
    metadata: dict[str, Any] | None = None,
) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=type,
        author=author,
        timestamp=timestamp,
        content=content,
        metadata=metadata or {},
    )


def _agent(
    *,
    agent_id: str = "tester",
    cooldown_seconds: int = 0,
    triggers: list[RegexTrigger | EventTypeTrigger | StateChangeTrigger] | None = None,
) -> Agent:
    speaking_triggers = triggers or []
    return Agent(
        id=agent_id,
        role="r",
        persona="p",
        llm_config=_LLM,
        cooldown_seconds=cooldown_seconds,
        speaking_triggers=speaking_triggers,
    )


def _regex_trigger(pattern: str) -> RegexTrigger:
    return RegexTrigger(pattern=pattern)


def _event_type_trigger(event_type: EventType) -> EventTypeTrigger:
    return EventTypeTrigger(event_type=event_type)


def _state_change_trigger(target_state: str) -> StateChangeTrigger:
    return StateChangeTrigger(target_state=target_state)


def _registry(*items: tuple[str, int, str]) -> dict[tuple[str, int], re.Pattern[str]]:
    """Build a regex_registry from (agent_id, trigger_index, pattern) tuples."""
    return {(aid, idx): re.compile(pat) for aid, idx, pat in items}


# ---------------------------------------------------------------------------
# 1. Empty triggers
# ---------------------------------------------------------------------------


def test_no_triggers_configured() -> None:
    agent = _agent(triggers=[])
    ev = _make_event()
    result = should_agent_speak(agent, [], current_event=ev, regex_registry={})
    assert result.speak is False
    assert result.reason == "no_triggers_configured"


# ---------------------------------------------------------------------------
# 2. Cooldown checks — unit conversion regression tests
# ---------------------------------------------------------------------------


def test_cooldown_blocks_when_30s_elapsed_but_cooldown_60s() -> None:
    """Regression: cooldown_seconds=60; last utterance 30 000 ms ago → BLOCKED.

    If the code uses ms instead of s, 30 000 < 60 would pass (wrong);
    the correct test: 30s elapsed < 60s cooldown → blocked.
    """
    agent = _agent(
        agent_id="a",
        cooldown_seconds=60,
        triggers=[_event_type_trigger(EventType.HYPOTHESIS)],
    )
    ts_now = TimestampMs(1_000_000)
    ts_30s_ago = TimestampMs(ts_now - 30_000)  # 30 000 ms = 30 s ago
    prior_utterance = _make_event(
        type=EventType.UTTERANCE, author="agent:a", timestamp=ts_30s_ago, content=""
    )
    current = _make_event(type=EventType.HYPOTHESIS, content="hypothesis text", timestamp=ts_now)
    result = should_agent_speak(
        agent,
        [prior_utterance],
        current_event=current,
        regex_registry={},
    )
    assert result.speak is False
    assert result.reason == "cooldown_active"
    # cooldown_remaining_s should be ~30 s (not ~29970 s which would signal ms bug)
    assert result.cooldown_remaining_s is not None
    assert 25.0 <= result.cooldown_remaining_s <= 35.0


def test_cooldown_passes_when_90s_elapsed_and_cooldown_60s() -> None:
    """Regression: cooldown_seconds=60; last utterance 90 000 ms ago → NOT blocked.

    If the code uses ms instead of s, 90 000 >= 60 passes (correct by accident);
    but with 90_000 ms vs 60 s the CORRECT path only works with /1000.0 conversion.
    """
    agent = _agent(
        agent_id="a",
        cooldown_seconds=60,
        triggers=[_event_type_trigger(EventType.HYPOTHESIS)],
    )
    ts_now = TimestampMs(1_000_000)
    ts_90s_ago = TimestampMs(ts_now - 90_000)  # 90 000 ms = 90 s ago
    prior_utterance = _make_event(
        type=EventType.UTTERANCE, author="agent:a", timestamp=ts_90s_ago, content=""
    )
    current = _make_event(type=EventType.HYPOTHESIS, content="hypothesis text", timestamp=ts_now)
    result = should_agent_speak(
        agent,
        [prior_utterance],
        current_event=current,
        regex_registry={},
    )
    assert result.speak is True
    assert result.reason == "trigger_matched"


def test_cooldown_remaining_s_correct_units() -> None:
    """cooldown_remaining_s should be in seconds, not milliseconds."""
    agent = _agent(agent_id="a", cooldown_seconds=60, triggers=[_regex_trigger("x")])
    ts_now = TimestampMs(1_000_000)
    ts_10s_ago = TimestampMs(ts_now - 10_000)
    prior = _make_event(
        type=EventType.UTTERANCE, author="agent:a", timestamp=ts_10s_ago, content=""
    )
    current = _make_event(content="hello world", timestamp=ts_now)
    result = should_agent_speak(
        agent, [prior], current_event=current, regex_registry=_registry(("a", 0, "x"))
    )
    assert result.reason == "cooldown_active"
    assert result.cooldown_remaining_s is not None
    # Should be ~50 s remaining (not ~49990 s which would signal ms bug)
    assert 45.0 <= result.cooldown_remaining_s <= 55.0


def test_cooldown_zero_never_blocks() -> None:
    """Agent with cooldown_seconds=0 should never be blocked by cooldown."""
    agent = _agent(agent_id="a", cooldown_seconds=0, triggers=[_regex_trigger("x")])
    ts_now = TimestampMs(1_000_000)
    prior = _make_event(type=EventType.UTTERANCE, author="agent:a", timestamp=ts_now, content="")
    current = _make_event(content="x matches", timestamp=ts_now)
    result = should_agent_speak(
        agent,
        [prior],
        current_event=current,
        regex_registry=_registry(("a", 0, "x")),
    )
    assert result.reason == "trigger_matched"
    assert result.speak is True


def test_cooldown_no_prior_utterance_in_snapshot() -> None:
    """No prior utterance → cooldown is not active regardless of cooldown_seconds."""
    agent = _agent(agent_id="a", cooldown_seconds=3600, triggers=[_regex_trigger("hello")])
    current = _make_event(content="say hello world")
    result = should_agent_speak(
        agent, [], current_event=current, regex_registry=_registry(("a", 0, "hello"))
    )
    assert result.speak is True
    assert result.reason == "trigger_matched"


# ---------------------------------------------------------------------------
# 3. Regex trigger
# ---------------------------------------------------------------------------


def test_regex_trigger_matches() -> None:
    agent = _agent(agent_id="a", triggers=[_regex_trigger("hello")])
    current = _make_event(content="say hello world")
    result = should_agent_speak(
        agent, [], current_event=current, regex_registry=_registry(("a", 0, "hello"))
    )
    assert result.speak is True
    assert result.reason == "trigger_matched"
    assert result.matched_trigger_index == 0


def test_regex_trigger_no_match() -> None:
    agent = _agent(agent_id="a", triggers=[_regex_trigger("goodbye")])
    current = _make_event(content="say hello world")
    result = should_agent_speak(
        agent, [], current_event=current, regex_registry=_registry(("a", 0, "goodbye"))
    )
    assert result.speak is False
    assert result.reason == "no_trigger_matched"


def test_regex_registry_miss_raises_speaking_trigger_error() -> None:
    """Missing regex_registry entry raises SpeakingTriggerError."""
    agent = _agent(agent_id="a", triggers=[_regex_trigger("hello")])
    current = _make_event(content="hello")
    with pytest.raises(SpeakingTriggerError) as exc_info:
        should_agent_speak(agent, [], current_event=current, regex_registry={})
    assert exc_info.value.agent_id == "a"
    assert exc_info.value.trigger_index == 0


# ---------------------------------------------------------------------------
# 4. EventTypeTrigger
# ---------------------------------------------------------------------------


def test_event_type_trigger_matches() -> None:
    agent = _agent(agent_id="a", triggers=[_event_type_trigger(EventType.HYPOTHESIS)])
    current = _make_event(type=EventType.HYPOTHESIS, content="new hypothesis")
    result = should_agent_speak(agent, [], current_event=current, regex_registry={})
    assert result.speak is True
    assert result.matched_trigger_index == 0


def test_event_type_trigger_no_match() -> None:
    agent = _agent(agent_id="a", triggers=[_event_type_trigger(EventType.HYPOTHESIS)])
    current = _make_event(type=EventType.USER_INPUT, content="user speaks")
    result = should_agent_speak(agent, [], current_event=current, regex_registry={})
    assert result.speak is False
    assert result.reason == "no_trigger_matched"


# ---------------------------------------------------------------------------
# 5. StateChangeTrigger
# ---------------------------------------------------------------------------


def test_state_change_trigger_matches_typed_metadata() -> None:
    """StateChangeTrigger reads typed StateTransitionMeta.new_state (R0-B 🔴#2)."""
    agent = _agent(agent_id="a", triggers=[_state_change_trigger("research")])
    current = _make_event(
        type=EventType.STATE_TRANSITION,
        content="",
        metadata={"new_state": "research"},
    )
    result = should_agent_speak(agent, [], current_event=current, regex_registry={})
    assert result.speak is True
    assert result.matched_trigger_index == 0


def test_state_change_trigger_wrong_state() -> None:
    agent = _agent(agent_id="a", triggers=[_state_change_trigger("research")])
    current = _make_event(
        type=EventType.STATE_TRANSITION,
        content="",
        metadata={"new_state": "bug_fix"},
    )
    result = should_agent_speak(agent, [], current_event=current, regex_registry={})
    assert result.speak is False
    assert result.reason == "no_trigger_matched"


def test_state_change_trigger_wrong_event_type() -> None:
    """StateChangeTrigger only fires on STATE_TRANSITION events."""
    agent = _agent(agent_id="a", triggers=[_state_change_trigger("research")])
    current = _make_event(type=EventType.USER_INPUT, content="not a state transition")
    result = should_agent_speak(agent, [], current_event=current, regex_registry={})
    assert result.speak is False


# ---------------------------------------------------------------------------
# 6. Multi-trigger: first match wins (list order)
# ---------------------------------------------------------------------------


def test_first_trigger_wins_short_circuit() -> None:
    agent = _agent(
        agent_id="a",
        triggers=[
            _regex_trigger("hello"),
            _event_type_trigger(EventType.HYPOTHESIS),
        ],
    )
    # Both would match: content has "hello" AND type is HYPOTHESIS
    current = _make_event(type=EventType.HYPOTHESIS, content="say hello hypothesis")
    result = should_agent_speak(
        agent, [], current_event=current, regex_registry=_registry(("a", 0, "hello"))
    )
    assert result.speak is True
    assert result.matched_trigger_index == 0  # regex at index 0 wins, not event_type at 1


def test_second_trigger_wins_when_first_no_match() -> None:
    agent = _agent(
        agent_id="a",
        triggers=[
            _regex_trigger("goodbye"),
            _event_type_trigger(EventType.HYPOTHESIS),
        ],
    )
    current = _make_event(type=EventType.HYPOTHESIS, content="hypothesis text")
    result = should_agent_speak(
        agent, [], current_event=current, regex_registry=_registry(("a", 0, "goodbye"))
    )
    assert result.speak is True
    assert result.matched_trigger_index == 1  # event_type at index 1


def test_all_three_trigger_types_cross_trigger() -> None:
    """Agent with all three trigger types; state_change is third."""
    agent = _agent(
        agent_id="a",
        triggers=[
            _regex_trigger("xyz"),
            _event_type_trigger(EventType.DECISION),
            _state_change_trigger("research"),
        ],
    )
    # Only state_change matches
    current = _make_event(
        type=EventType.STATE_TRANSITION,
        content="",
        metadata={"new_state": "research"},
    )
    result = should_agent_speak(
        agent, [], current_event=current, regex_registry=_registry(("a", 0, "xyz"))
    )
    assert result.speak is True
    assert result.matched_trigger_index == 2


# ---------------------------------------------------------------------------
# 7. Cooldown elapsed → triggers evaluate
# ---------------------------------------------------------------------------


def test_cooldown_elapsed_then_trigger_evaluated() -> None:
    agent = _agent(
        agent_id="a",
        cooldown_seconds=10,
        triggers=[_regex_trigger("hello")],
    )
    ts_now = TimestampMs(1_000_000)
    ts_15s_ago = TimestampMs(ts_now - 15_000)  # 15s > 10s cooldown → elapsed
    prior = _make_event(
        type=EventType.UTTERANCE, author="agent:a", timestamp=ts_15s_ago, content=""
    )
    current = _make_event(content="say hello", timestamp=ts_now)
    result = should_agent_speak(
        agent, [prior], current_event=current, regex_registry=_registry(("a", 0, "hello"))
    )
    assert result.speak is True
    assert result.reason == "trigger_matched"


# ---------------------------------------------------------------------------
# 8. matched_trigger_index accuracy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("trigger_index", [0, 1, 2])
def test_matched_trigger_index_correct_position(trigger_index: int) -> None:
    """matched_trigger_index should equal the 0-based position of the matching trigger."""
    triggers = cast(
        list[RegexTrigger | EventTypeTrigger | StateChangeTrigger],
        [_event_type_trigger(EventType.MILESTONE)] * trigger_index
        + [_event_type_trigger(EventType.DECISION)],
    )
    agent = _agent(agent_id="a", triggers=triggers)
    current = _make_event(type=EventType.DECISION, content="a decision was made")
    result = should_agent_speak(agent, [], current_event=current, regex_registry={})
    assert result.speak is True
    assert result.matched_trigger_index == trigger_index
