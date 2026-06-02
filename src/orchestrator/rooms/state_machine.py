"""Per-RoomType state machine: per-RoomType Literals + `next_room_state`.

Implements ADR-012 Decisions 1 and 2 (amended P2.7-S1):
- Decision 1: code-driven, event-triggered state machines per RoomType.
- Decision 2: per-RoomType `Literal` state sets (Research fully implemented;
  all four scaffold RoomTypes now have real event-triggered transition tables
  per the ADR-012 P2.7-S1 amendment).

``next_room_state`` is a **pure function**: no I/O, no LLM, no event_store
calls.  The caller (``RoomRuntime``) passes in the event-stream snapshot and
the current event; this function returns a typed transition or ``None``.

**Recency window**: the function only examines the last ``_RESEARCH_WINDOW``
(50) events of the snapshot for Research rooms.  This is a bounded read
rather than a full-stream scan — matching the ADR-012 D1 "same snapshot
semantic as ``should_agent_speak``" pattern. The window size is documented
here and may be made configurable per RoomType in P1.6+.

Transition rules (Research):

| From            | To               | Trigger                                               |
|-----------------|------------------|-------------------------------------------------------|
| setup           | exploration      | first ``utterance`` event (current_event)             |
| exploration     | divergence       | ≥2 hypothesis events in snapshot + current hypothesis |
| divergence      | convergence      | ``user_input`` content matches decide-intent regex    |
| convergence     | snapshot_pending | ``decision`` event appended (current_event)           |
| snapshot_pending| closed           | ``summary_snapshot`` event appended (current_event)   |

Transition rules (BugFix):

| From         | To           | Trigger           | rule_matched                     |
|--------------|--------------|-------------------|----------------------------------|
| setup        | reproduced   | OBSERVATION       | observation_triggers_reproduced  |
| reproduced   | diagnosed    | HYPOTHESIS        | hypothesis_triggers_diagnosed    |
| diagnosed    | fix_proposed | DECISION          | decision_triggers_fix_proposed   |
| fix_proposed | closed       | SUMMARY_SNAPSHOT  | snapshot_triggers_closed         |

Transition rules (CodeReview):

| From              | To                | Trigger          | rule_matched                        |
|-------------------|-------------------|------------------|-------------------------------------|
| setup             | reviewing         | OBSERVATION      | observation_triggers_reviewing      |
| reviewing         | changes_requested | REJECTION        | rejection_triggers_changes_requested|
| changes_requested | approved          | DECISION         | decision_triggers_approved          |
| approved          | closed            | SUMMARY_SNAPSHOT | snapshot_triggers_closed            |

Transition rules (IdeaValidation):

| From       | To         | Trigger           | rule_matched                    |
|------------|------------|-------------------|---------------------------------|
| setup      | pitching   | UTTERANCE         | utterance_triggers_pitching     |
| pitching   | validating | HYPOTHESIS        | hypothesis_triggers_validating  |
| validating | decided    | DECISION          | decision_triggers_decided       |
| decided    | closed     | SUMMARY_SNAPSHOT  | snapshot_triggers_closed        |

Transition rules (FreeChat):

| From   | To     | Trigger           | rule_matched               |
|--------|--------|-------------------|----------------------------|
| setup  | active | UTTERANCE         | utterance_triggers_active  |
| active | closed | SUMMARY_SNAPSHOT  | snapshot_triggers_closed   |

No LLM imports — enforced by
``test_constitution_no_llm_calls_in_rooms_module`` (ADR-012 D7).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from orchestrator.core.event import Event, EventType
from orchestrator.core.room import Room, RoomType
from orchestrator.rooms.exceptions import RoomStateError

# ---------------------------------------------------------------------------
# Per-RoomType state Literals (ADR-012 D2)
# ---------------------------------------------------------------------------

ResearchRoomState = Literal[
    "setup",
    "exploration",
    "divergence",
    "convergence",
    "snapshot_pending",
    "closed",
]

BugFixRoomState = Literal["setup", "reproduced", "diagnosed", "fix_proposed", "closed"]
CodeReviewRoomState = Literal["setup", "reviewing", "changes_requested", "approved", "closed"]
IdeaValidationRoomState = Literal["setup", "pitching", "validating", "decided", "closed"]
FreeChatRoomState = Literal["setup", "active", "closed"]

RoomState = (
    ResearchRoomState
    | BugFixRoomState
    | CodeReviewRoomState
    | IdeaValidationRoomState
    | FreeChatRoomState
)

# Valid state sets per RoomType — used for defensive validation in
# ``RoomStateError`` guard.
_VALID_STATES: dict[RoomType, frozenset[str]] = {
    RoomType.RESEARCH: frozenset(
        {"setup", "exploration", "divergence", "convergence", "snapshot_pending", "closed"}
    ),
    RoomType.BUG_FIX: frozenset({"setup", "reproduced", "diagnosed", "fix_proposed", "closed"}),
    RoomType.CODE_REVIEW: frozenset(
        {"setup", "reviewing", "changes_requested", "approved", "closed"}
    ),
    RoomType.IDEA_VALIDATION: frozenset({"setup", "pitching", "validating", "decided", "closed"}),
    RoomType.FREE_CHAT: frozenset({"setup", "active", "closed"}),
}

# ---------------------------------------------------------------------------
# Recency window
# ---------------------------------------------------------------------------

#: Number of most-recent snapshot events examined by Research transitions.
#: Bounded read — not whole-stream (ADR-012 D1 recency-window self-discovery).
_RESEARCH_WINDOW: int = 50

# ---------------------------------------------------------------------------
# Decide-intent regex (divergence → convergence trigger)
# ---------------------------------------------------------------------------

_DECIDE_INTENT_RE: re.Pattern[str] = re.compile(r"(?i)\b(decide|choose|pick|finalize)\b")

# ---------------------------------------------------------------------------
# RoomStateTransition model
# ---------------------------------------------------------------------------


class RoomStateTransition(BaseModel):
    """Typed result of a state-machine transition.

    Frozen + extra-forbid per ``test-coverage-standard.md`` §6.

    ``rule_matched`` is a short rule identifier that lets callers log or
    trace which transition rule fired — e.g.,
    ``"hypothesis_density_triggers_divergence"``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prior_state: str
    new_state: str
    triggering_event_type: EventType
    rule_matched: str


# ---------------------------------------------------------------------------
# Per-RoomType transition functions (internal)
# ---------------------------------------------------------------------------


def _next_research_state(
    room: Room,
    snapshot_window: list[Event],
    current_event: Event,
) -> RoomStateTransition | None:
    """Research state machine.

    ``snapshot_window`` is the last ``_RESEARCH_WINDOW`` events from the
    caller-supplied snapshot (already sliced by ``next_room_state``).
    ``current_event`` is NOT included in ``snapshot_window`` — the caller
    (``RoomRuntime``) passes the snapshot taken *before* appending the
    current event (ADR-012 D1 snapshot semantic).
    """
    state = room.state

    if state == "setup":
        # setup → exploration: first utterance event by any agent.
        if current_event.type == EventType.UTTERANCE:
            new_state = "exploration"
            _guard_valid_state(room, new_state, "setup_to_exploration")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.UTTERANCE,
                rule_matched="setup_to_exploration",
            )
        return None

    if state == "exploration":
        # exploration → divergence: ≥2 hypothesis events in snapshot
        # AND current_event is also a hypothesis.
        if current_event.type == EventType.HYPOTHESIS:
            hypothesis_count = sum(1 for e in snapshot_window if e.type == EventType.HYPOTHESIS)
            if hypothesis_count >= 2:
                new_state = "divergence"
                _guard_valid_state(room, new_state, "hypothesis_density_triggers_divergence")
                return RoomStateTransition(
                    prior_state=state,
                    new_state=new_state,
                    triggering_event_type=EventType.HYPOTHESIS,
                    rule_matched="hypothesis_density_triggers_divergence",
                )
        return None

    if state == "divergence":
        # divergence → convergence: user_input with decide-intent content.
        if current_event.type == EventType.USER_INPUT and _DECIDE_INTENT_RE.search(
            current_event.content
        ):
            new_state = "convergence"
            _guard_valid_state(room, new_state, "user_decide_intent_triggers_convergence")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.USER_INPUT,
                rule_matched="user_decide_intent_triggers_convergence",
            )
        return None

    if state == "convergence":
        # convergence → snapshot_pending: decision event appended.
        if current_event.type == EventType.DECISION:
            new_state = "snapshot_pending"
            _guard_valid_state(room, new_state, "decision_triggers_snapshot_pending")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.DECISION,
                rule_matched="decision_triggers_snapshot_pending",
            )
        return None

    if state == "snapshot_pending":
        # snapshot_pending → closed: summary_snapshot event appended.
        if current_event.type == EventType.SUMMARY_SNAPSHOT:
            new_state = "closed"
            _guard_valid_state(room, new_state, "summary_snapshot_triggers_closed")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.SUMMARY_SNAPSHOT,
                rule_matched="summary_snapshot_triggers_closed",
            )
        return None

    # state == "closed" or any other state: no automatic transitions.
    return None


def _next_bug_fix_state(
    room: Room,
    snapshot_window: list[Event],
    current_event: Event,
) -> RoomStateTransition | None:
    """BugFix state machine (ADR-012 P2.7-S1 amendment).

    Arcs: setup→reproduced (OBSERVATION), reproduced→diagnosed (HYPOTHESIS),
    diagnosed→fix_proposed (DECISION), fix_proposed→closed (SUMMARY_SNAPSHOT).
    """
    state = room.state

    if state == "setup":
        if current_event.type == EventType.OBSERVATION:
            new_state = "reproduced"
            _guard_valid_state(room, new_state, "observation_triggers_reproduced")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.OBSERVATION,
                rule_matched="observation_triggers_reproduced",
            )
        return None

    if state == "reproduced":
        if current_event.type == EventType.HYPOTHESIS:
            new_state = "diagnosed"
            _guard_valid_state(room, new_state, "hypothesis_triggers_diagnosed")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.HYPOTHESIS,
                rule_matched="hypothesis_triggers_diagnosed",
            )
        return None

    if state == "diagnosed":
        if current_event.type == EventType.DECISION:
            new_state = "fix_proposed"
            _guard_valid_state(room, new_state, "decision_triggers_fix_proposed")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.DECISION,
                rule_matched="decision_triggers_fix_proposed",
            )
        return None

    if state == "fix_proposed":
        if current_event.type == EventType.SUMMARY_SNAPSHOT:
            new_state = "closed"
            _guard_valid_state(room, new_state, "snapshot_triggers_closed")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.SUMMARY_SNAPSHOT,
                rule_matched="snapshot_triggers_closed",
            )
        return None

    # state == "closed" or any other state: no automatic transitions.
    return None


def _next_code_review_state(
    room: Room,
    snapshot_window: list[Event],
    current_event: Event,
) -> RoomStateTransition | None:
    """CodeReview state machine (ADR-012 P2.7-S1 amendment).

    Arcs: setup→reviewing (OBSERVATION), reviewing→changes_requested (REJECTION),
    changes_requested→approved (DECISION), approved→closed (SUMMARY_SNAPSHOT).
    """
    state = room.state

    if state == "setup":
        if current_event.type == EventType.OBSERVATION:
            new_state = "reviewing"
            _guard_valid_state(room, new_state, "observation_triggers_reviewing")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.OBSERVATION,
                rule_matched="observation_triggers_reviewing",
            )
        return None

    if state == "reviewing":
        if current_event.type == EventType.REJECTION:
            new_state = "changes_requested"
            _guard_valid_state(room, new_state, "rejection_triggers_changes_requested")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.REJECTION,
                rule_matched="rejection_triggers_changes_requested",
            )
        return None

    if state == "changes_requested":
        if current_event.type == EventType.DECISION:
            new_state = "approved"
            _guard_valid_state(room, new_state, "decision_triggers_approved")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.DECISION,
                rule_matched="decision_triggers_approved",
            )
        return None

    if state == "approved":
        if current_event.type == EventType.SUMMARY_SNAPSHOT:
            new_state = "closed"
            _guard_valid_state(room, new_state, "snapshot_triggers_closed")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.SUMMARY_SNAPSHOT,
                rule_matched="snapshot_triggers_closed",
            )
        return None

    # state == "closed" or any other state: no automatic transitions.
    return None


def _next_idea_validation_state(
    room: Room,
    snapshot_window: list[Event],
    current_event: Event,
) -> RoomStateTransition | None:
    """IdeaValidation state machine (ADR-012 P2.7-S1 amendment).

    Arcs: setup→pitching (UTTERANCE), pitching→validating (HYPOTHESIS),
    validating→decided (DECISION), decided→closed (SUMMARY_SNAPSHOT).
    """
    state = room.state

    if state == "setup":
        if current_event.type == EventType.UTTERANCE:
            new_state = "pitching"
            _guard_valid_state(room, new_state, "utterance_triggers_pitching")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.UTTERANCE,
                rule_matched="utterance_triggers_pitching",
            )
        return None

    if state == "pitching":
        if current_event.type == EventType.HYPOTHESIS:
            new_state = "validating"
            _guard_valid_state(room, new_state, "hypothesis_triggers_validating")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.HYPOTHESIS,
                rule_matched="hypothesis_triggers_validating",
            )
        return None

    if state == "validating":
        if current_event.type == EventType.DECISION:
            new_state = "decided"
            _guard_valid_state(room, new_state, "decision_triggers_decided")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.DECISION,
                rule_matched="decision_triggers_decided",
            )
        return None

    if state == "decided":
        if current_event.type == EventType.SUMMARY_SNAPSHOT:
            new_state = "closed"
            _guard_valid_state(room, new_state, "snapshot_triggers_closed")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.SUMMARY_SNAPSHOT,
                rule_matched="snapshot_triggers_closed",
            )
        return None

    # state == "closed" or any other state: no automatic transitions.
    return None


def _next_free_chat_state(
    room: Room,
    snapshot_window: list[Event],
    current_event: Event,
) -> RoomStateTransition | None:
    """FreeChat state machine (ADR-012 P2.7-S1 amendment).

    Arcs: setup→active (UTTERANCE), active→closed (SUMMARY_SNAPSHOT).
    """
    state = room.state

    if state == "setup":
        if current_event.type == EventType.UTTERANCE:
            new_state = "active"
            _guard_valid_state(room, new_state, "utterance_triggers_active")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.UTTERANCE,
                rule_matched="utterance_triggers_active",
            )
        return None

    if state == "active":
        if current_event.type == EventType.SUMMARY_SNAPSHOT:
            new_state = "closed"
            _guard_valid_state(room, new_state, "snapshot_triggers_closed")
            return RoomStateTransition(
                prior_state=state,
                new_state=new_state,
                triggering_event_type=EventType.SUMMARY_SNAPSHOT,
                rule_matched="snapshot_triggers_closed",
            )
        return None

    # state == "closed" or any other state: no automatic transitions.
    return None


# ---------------------------------------------------------------------------
# Internal guard
# ---------------------------------------------------------------------------


def _guard_valid_state(room: Room, new_state: str, rule: str) -> None:
    """Raise ``RoomStateError`` if ``new_state`` is not valid for ``room.type``.

    Defensive check: a transition rule should never produce a state outside
    the per-RoomType Literal.  If it does, it is a code defect — surface it
    loudly rather than writing an invalid ``state_transition`` event.
    """
    valid = _VALID_STATES.get(room.type, frozenset())
    if new_state not in valid:
        raise RoomStateError(
            room_id=room.id,
            current_state=room.state,
            attempted_transition_rule=rule,
            message=(
                f"Room {room.id!r} (type={room.type.value!r}): transition rule "
                f"{rule!r} produced state {new_state!r}, which is not in the "
                f"valid state set {sorted(valid)!r}"
            ),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def next_room_state(
    room: Room,
    event_stream_snapshot: list[Event],
    *,
    current_event: Event,
) -> RoomStateTransition | None:
    """Return a typed state transition when the current event triggers one.

    Pure function — no I/O, no LLM, no event_store calls.

    ``event_stream_snapshot`` is the event list taken **before** appending
    ``current_event`` (the ``RoomRuntime`` caller follows ADR-012 D1 snapshot
    semantics).  For Research rooms only the last ``_RESEARCH_WINDOW`` (50)
    events are examined (recency window; ADR-012 D1 self-discovery #2).

    Returns ``None`` for the vast majority of events (most events do not
    trigger a transition).  The caller persists the returned
    ``RoomStateTransition`` by appending a ``state_transition`` event with
    ``StateTransitionMeta(prior_state=…, new_state=…)``.

    Raises:
        RoomStateError: a transition rule fired but produced an invalid
            state (internal contract violation — defensive guard).
    """
    # Slice to recency window before dispatch.
    window = event_stream_snapshot[-_RESEARCH_WINDOW:]

    match room.type:
        case RoomType.RESEARCH:
            return _next_research_state(room, window, current_event)
        case RoomType.BUG_FIX:
            return _next_bug_fix_state(room, window, current_event)
        case RoomType.CODE_REVIEW:
            return _next_code_review_state(room, window, current_event)
        case RoomType.IDEA_VALIDATION:
            return _next_idea_validation_state(room, window, current_event)
        case RoomType.FREE_CHAT:
            return _next_free_chat_state(room, window, current_event)
        case _:  # pragma: no cover — exhaustive; new RoomType requires update
            raise RoomStateError(
                room_id=room.id,
                current_state=room.state,
                attempted_transition_rule="unknown_room_type_dispatch",
                message=f"No state machine registered for RoomType {room.type!r}",
            )
