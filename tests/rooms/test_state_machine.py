"""Tests for rooms/state_machine.py — per-RoomType Literals + next_room_state.

Coverage:
  1. Research happy paths: 5 transitions (setup→exploration, exploration→divergence,
     divergence→convergence, convergence→snapshot_pending, snapshot_pending→closed).
  2. No-transition case: events that should NOT fire a transition in a given state.
  3. Cycle case: exploration → divergence fires twice (no one-shot block).
  4. Scaffold RoomType: next_room_state returns None for any event.
  5. Recency window: hypothesis events older than window N are excluded.
  6. RoomStateError: raised on internal contract violation.
  7. RoomStateTransition schema invariants: frozen + extra-forbid.

Per test-coverage-standard.md:
  §4: RoomStateError payload fields (room_id, current_state, attempted_transition_rule).
  §6: RoomStateTransition frozen + extra-forbid.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    TimestampMs,
    generate_event_id,
    generate_room_id,
)
from orchestrator.core.room import Room, RoomType
from orchestrator.rooms.exceptions import RoomStateError
from orchestrator.rooms.state_machine import (
    _RESEARCH_WINDOW,
    RoomStateTransition,
    _guard_valid_state,
    next_room_state,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = TimestampMs(1_000_000)


def _make_room(
    *,
    room_type: RoomType = RoomType.RESEARCH,
    state: str = "setup",
) -> Room:
    return Room(id=generate_room_id(), type=room_type, state=state)


def _make_event(
    *,
    event_type: EventType = EventType.USER_INPUT,
    content: str = "hello",
    author: str = "user",
    room_id: RoomId | None = None,
    metadata: dict[str, Any] | None = None,
) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id or generate_room_id(),
        type=event_type,
        author=author,
        timestamp=_TS,
        content=content,
        metadata=metadata or {},
    )


def _hypothesis_event(room_id: RoomId | None = None) -> Event:
    return _make_event(
        event_type=EventType.HYPOTHESIS,
        content="my hypothesis",
        author="agent:prober",
        room_id=room_id,
        metadata={"confidence": 0.7, "based_on": []},
    )


def _utterance_event(room_id: RoomId | None = None) -> Event:
    return _make_event(
        event_type=EventType.UTTERANCE,
        content="let's start",
        author="agent:skeptic",
        room_id=room_id,
    )


def _decision_event(room_id: RoomId | None = None) -> Event:
    return _make_event(
        event_type=EventType.DECISION,
        content="we decided X",
        author="agent:operator",
        room_id=room_id,
        metadata={"based_on": [generate_event_id()], "trade_offs": {}},
    )


def _summary_snapshot_event(room_id: RoomId | None = None) -> Event:
    return _make_event(
        event_type=EventType.SUMMARY_SNAPSHOT,
        content="summary here",
        author="agent:logger",
        room_id=room_id,
    )


# ---------------------------------------------------------------------------
# 1. Research happy paths
# ---------------------------------------------------------------------------


class TestResearchTransitionHappyPaths:
    def test_setup_to_exploration_on_utterance(self) -> None:
        """setup → exploration fires on first utterance event."""
        room = _make_room(state="setup")
        snapshot: list[Event] = []
        current = _utterance_event()

        result = next_room_state(room, snapshot, current_event=current)

        assert result is not None
        assert result.prior_state == "setup"
        assert result.new_state == "exploration"
        assert result.triggering_event_type == EventType.UTTERANCE
        assert result.rule_matched == "setup_to_exploration"

    def test_exploration_to_divergence_on_third_hypothesis(self) -> None:
        """exploration → divergence: snapshot has ≥2 hypotheses + current is hypothesis."""
        room = _make_room(state="exploration")
        # Two hypotheses already in snapshot.
        snapshot: list[Event] = [_hypothesis_event(), _hypothesis_event()]
        current = _hypothesis_event()

        result = next_room_state(room, snapshot, current_event=current)

        assert result is not None
        assert result.prior_state == "exploration"
        assert result.new_state == "divergence"
        assert result.triggering_event_type == EventType.HYPOTHESIS
        assert result.rule_matched == "hypothesis_density_triggers_divergence"

    def test_divergence_to_convergence_on_decide_intent(self) -> None:
        """divergence → convergence fires on user_input with decide-intent keyword."""
        room = _make_room(state="divergence")
        snapshot: list[Event] = []
        current = _make_event(
            event_type=EventType.USER_INPUT,
            content="Let's decide on option A",
        )

        result = next_room_state(room, snapshot, current_event=current)

        assert result is not None
        assert result.prior_state == "divergence"
        assert result.new_state == "convergence"
        assert result.triggering_event_type == EventType.USER_INPUT
        assert result.rule_matched == "user_decide_intent_triggers_convergence"

    def test_convergence_to_snapshot_pending_on_decision(self) -> None:
        """convergence → snapshot_pending fires on decision event."""
        room = _make_room(state="convergence")
        snapshot: list[Event] = []
        current = _decision_event()

        result = next_room_state(room, snapshot, current_event=current)

        assert result is not None
        assert result.prior_state == "convergence"
        assert result.new_state == "snapshot_pending"
        assert result.triggering_event_type == EventType.DECISION
        assert result.rule_matched == "decision_triggers_snapshot_pending"

    def test_snapshot_pending_to_closed_on_summary_snapshot(self) -> None:
        """snapshot_pending → closed fires on summary_snapshot event."""
        room = _make_room(state="snapshot_pending")
        snapshot: list[Event] = []
        current = _summary_snapshot_event()

        result = next_room_state(room, snapshot, current_event=current)

        assert result is not None
        assert result.prior_state == "snapshot_pending"
        assert result.new_state == "closed"
        assert result.triggering_event_type == EventType.SUMMARY_SNAPSHOT
        assert result.rule_matched == "summary_snapshot_triggers_closed"


# ---------------------------------------------------------------------------
# 2. No-transition cases
# ---------------------------------------------------------------------------


class TestNoTransitionCases:
    def test_utterance_in_convergence_does_not_transition(self) -> None:
        """An utterance in convergence state does NOT trigger any transition."""
        room = _make_room(state="convergence")
        snapshot: list[Event] = []
        current = _utterance_event()

        result = next_room_state(room, snapshot, current_event=current)

        assert result is None

    def test_setup_does_not_transition_on_user_input(self) -> None:
        """setup state only transitions on utterance; user_input does nothing."""
        room = _make_room(state="setup")
        snapshot: list[Event] = []
        current = _make_event(event_type=EventType.USER_INPUT, content="hello")

        result = next_room_state(room, snapshot, current_event=current)

        assert result is None

    def test_exploration_does_not_transition_with_only_one_hypothesis_in_snapshot(
        self,
    ) -> None:
        """exploration → divergence requires ≥2 hypotheses in snapshot; 1 is not enough."""
        room = _make_room(state="exploration")
        snapshot: list[Event] = [_hypothesis_event()]  # only 1 in snapshot
        current = _hypothesis_event()  # current is hypothesis too

        result = next_room_state(room, snapshot, current_event=current)

        assert result is None

    def test_divergence_user_input_without_decide_keyword_does_not_transition(
        self,
    ) -> None:
        """divergence: user_input without decide-intent keyword stays in divergence."""
        room = _make_room(state="divergence")
        snapshot: list[Event] = []
        current = _make_event(
            event_type=EventType.USER_INPUT,
            content="what about option B?",
        )

        result = next_room_state(room, snapshot, current_event=current)

        assert result is None

    def test_closed_state_no_transition(self) -> None:
        """closed state: no automatic transition for any event."""
        room = _make_room(state="closed")
        snapshot: list[Event] = [_hypothesis_event(), _hypothesis_event()]
        current = _utterance_event()

        result = next_room_state(room, snapshot, current_event=current)

        assert result is None


# ---------------------------------------------------------------------------
# 3. Cycle case: exploration → divergence can fire multiple times
# ---------------------------------------------------------------------------


class TestCycleCase:
    def test_exploration_to_divergence_fires_from_exploration_state_twice(self) -> None:
        """exploration → divergence has no one-shot block; fires whenever conditions hold."""
        room_state_1 = _make_room(state="exploration")
        snapshot = [_hypothesis_event(), _hypothesis_event()]
        current = _hypothesis_event()

        result_1 = next_room_state(room_state_1, snapshot, current_event=current)
        assert result_1 is not None
        assert result_1.new_state == "divergence"

        # Simulate a cycle: room returns to exploration (e.g., via runtime rollback
        # or re-entry); the transition fires again from a fresh exploration state.
        room_state_2 = _make_room(state="exploration")
        result_2 = next_room_state(room_state_2, snapshot, current_event=current)
        assert result_2 is not None
        assert result_2.new_state == "divergence"

    def test_decide_intent_regex_variants(self) -> None:
        """All decide-intent keywords fire the divergence → convergence transition."""
        room = _make_room(state="divergence")
        snapshot: list[Event] = []
        for keyword in ("decide", "choose", "pick", "finalize", "DECIDE", "Choose"):
            current = _make_event(
                event_type=EventType.USER_INPUT,
                content=f"Let's {keyword} now",
            )
            result = next_room_state(room, snapshot, current_event=current)
            assert result is not None, f"keyword {keyword!r} should trigger transition"
            assert result.new_state == "convergence"


# ---------------------------------------------------------------------------
# 4. Scaffold RoomType: always returns None
# ---------------------------------------------------------------------------


class TestScaffoldRoomTypes:
    @pytest.mark.parametrize(
        "room_type",
        [
            RoomType.BUG_FIX,
            RoomType.CODE_REVIEW,
            RoomType.IDEA_VALIDATION,
            RoomType.FREE_CHAT,
        ],
    )
    def test_scaffold_returns_none_for_any_event(self, room_type: RoomType) -> None:
        """Scaffold RoomTypes: next_room_state always returns None (no automatic transitions)."""
        room = _make_room(room_type=room_type, state="setup")
        snapshot: list[Event] = [_hypothesis_event(), _hypothesis_event()]
        for event_type in (
            EventType.UTTERANCE,
            EventType.HYPOTHESIS,
            EventType.USER_INPUT,
            EventType.DECISION,
            EventType.SUMMARY_SNAPSHOT,
        ):
            current = _make_event(event_type=event_type)
            result = next_room_state(room, snapshot, current_event=current)
            assert result is None, (
                f"RoomType.{room_type.name} should return None for {event_type.value}"
            )


# ---------------------------------------------------------------------------
# 5. Recency window: events older than N are excluded
# ---------------------------------------------------------------------------


class TestRecencyWindow:
    def test_hypothesis_beyond_window_is_excluded(self) -> None:
        """Hypothesis events outside the last _RESEARCH_WINDOW are not counted.

        Build a snapshot of (RESEARCH_WINDOW + 1) events where the oldest
        2 events are hypotheses but both fall outside the window; then
        add 1 hypothesis inside the window + current is hypothesis.
        With only 1 hypothesis in the window the threshold (≥2) is not met.
        """
        room = _make_room(state="exploration")

        # Two old hypotheses that will be outside the window.
        old_hyps = [_hypothesis_event(), _hypothesis_event()]
        # Fill the window with non-hypothesis events (RESEARCH_WINDOW items).
        filler = [_make_event(event_type=EventType.UTTERANCE) for _ in range(_RESEARCH_WINDOW - 1)]
        # One hypothesis inside the window (last slot of snapshot).
        recent_hyp = _hypothesis_event()

        # Snapshot order: [old hyps (2)] + [filler (N-1)] + [recent hyp (1)]
        # Total = 2 + (N-1) + 1 = N+2 events.
        # The window sees the last N events: [filler (N-1)] + [recent hyp (1)].
        # That is only 1 hypothesis in the window → threshold not met.
        snapshot = old_hyps + filler + [recent_hyp]

        current = _hypothesis_event()  # current is also hypothesis

        result = next_room_state(room, snapshot, current_event=current)

        # 1 hypothesis in window < 2 required → no transition.
        assert result is None

    def test_two_hypotheses_exactly_at_window_boundary_triggers(self) -> None:
        """Two hypotheses exactly within the window + current hypothesis → transition fires."""
        room = _make_room(state="exploration")

        # N-2 filler events + 2 hypotheses = exactly N events in snapshot.
        filler = [_make_event(event_type=EventType.UTTERANCE) for _ in range(_RESEARCH_WINDOW - 2)]
        in_window_hyps = [_hypothesis_event(), _hypothesis_event()]
        snapshot = filler + in_window_hyps  # length == _RESEARCH_WINDOW

        current = _hypothesis_event()

        result = next_room_state(room, snapshot, current_event=current)

        assert result is not None
        assert result.new_state == "divergence"


# ---------------------------------------------------------------------------
# 6. RoomStateError raised on invalid transition (defensive)
# ---------------------------------------------------------------------------


class TestRoomStateError:
    def test_room_state_error_raised_on_invalid_new_state(self) -> None:
        """_guard_valid_state raises RoomStateError with correct payload fields."""
        room = _make_room(room_type=RoomType.RESEARCH, state="exploration")
        invalid_new_state = "nonexistent_state"
        rule = "test_rule_identifier"

        with pytest.raises(RoomStateError) as exc_info:
            _guard_valid_state(room, invalid_new_state, rule)

        err = exc_info.value
        # §4 payload check: three structured fields.
        assert err.room_id == room.id
        assert err.current_state == "exploration"
        assert err.attempted_transition_rule == rule

    def test_room_state_error_message_is_informative(self) -> None:
        """RoomStateError default message includes room_id and rule name."""
        room = _make_room(room_type=RoomType.RESEARCH, state="setup")

        with pytest.raises(RoomStateError) as exc_info:
            _guard_valid_state(room, "bad_state", "my_rule")

        msg = str(exc_info.value)
        assert "my_rule" in msg
        assert room.id in msg


# ---------------------------------------------------------------------------
# 7. RoomStateTransition schema invariants (test-coverage-standard §6)
# ---------------------------------------------------------------------------


class TestRoomStateTransitionSchema:
    def test_frozen_prevents_mutation(self) -> None:
        """RoomStateTransition is frozen: direct attribute assignment raises."""
        transition = RoomStateTransition(
            prior_state="setup",
            new_state="exploration",
            triggering_event_type=EventType.UTTERANCE,
            rule_matched="setup_to_exploration",
        )
        with pytest.raises((TypeError, ValidationError)):
            transition.new_state = "divergence"

    def test_extra_fields_forbidden(self) -> None:
        """RoomStateTransition rejects extra fields (extra='forbid')."""
        with pytest.raises(ValidationError):
            RoomStateTransition(  # type: ignore[call-arg]
                prior_state="setup",
                new_state="exploration",
                triggering_event_type=EventType.UTTERANCE,
                rule_matched="setup_to_exploration",
                unexpected_field="oops",
            )

    def test_all_required_fields_present(self) -> None:
        """RoomStateTransition constructed successfully with all four fields."""
        transition = RoomStateTransition(
            prior_state="divergence",
            new_state="convergence",
            triggering_event_type=EventType.USER_INPUT,
            rule_matched="user_decide_intent_triggers_convergence",
        )
        assert transition.prior_state == "divergence"
        assert transition.new_state == "convergence"
        assert transition.triggering_event_type == EventType.USER_INPUT
        assert transition.rule_matched == "user_decide_intent_triggers_convergence"

    def test_missing_required_field_raises(self) -> None:
        """RoomStateTransition raises ValidationError when a required field is missing."""
        with pytest.raises(ValidationError):
            RoomStateTransition(  # type: ignore[call-arg]
                prior_state="setup",
                new_state="exploration",
                triggering_event_type=EventType.UTTERANCE,
                # rule_matched is missing
            )
