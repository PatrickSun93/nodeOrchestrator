"""Room runtime: per-turn orchestrator.

``run_turn`` is the integration site between the state machine, agent
filtering, and turn dispatch (ADR-012 D5). It orchestrates one turn:

  1. Take event-stream snapshot (ADR-011 D2 snapshot semantic).
  2. Evaluate ``next_room_state`` — if a transition fires, append a
     ``state_transition`` event with ``StateTransitionMeta``.
  3. Load-time filter: ``decide_agents_for_room`` by ``room_type``.
  4. Dispatch-time filter: keep agents whose ``applies_to.room_states``
     includes ``room.state`` (or is ``["*"]``).
  5. Dispatch via ``dispatch_turn``.

``room.state`` is NOT mutated by ``run_turn`` — the Room model is
frozen (Pydantic ``frozen=True``).  The state-machine transition takes
effect on the NEXT turn when the appended ``state_transition`` event
appears in that turn's snapshot.  This turn dispatches with the
pre-transition state, which is the correct causality: agents active in
state N respond to the event that triggered the transition to state N+1,
not to the new state they haven't "seen" yet.

No LLM imports — enforced by
``test_constitution_no_llm_calls_in_rooms_module`` (ADR-012 D7).
"""

from __future__ import annotations

import re

from orchestrator.agents.dispatch import LLMRouterProtocol, dispatch_turn
from orchestrator.agents.schema import Agent, TurnResult
from orchestrator.agents.selection import decide_agents_for_room
from orchestrator.core.event import (
    Event,
    EventType,
    StateTransitionMeta,
    generate_event_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room
from orchestrator.rooms.state_machine import next_room_state
from orchestrator.skills.schema import Skill


def run_turn(
    room: Room,
    current_event: Event,
    *,
    available_agents: dict[str, Agent],
    available_skills: dict[str, Skill],
    event_store: EventStore,
    llm_router: LLMRouterProtocol,
    regex_registry: dict[tuple[str, int], re.Pattern[str]],
) -> TurnResult:
    """Orchestrate one turn: state machine → agent filtering → dispatch.

    ``room.state`` is read but NOT mutated — the transition is persisted
    as a ``state_transition`` event; the Room object is unchanged.

    Args:
        room: The room this turn belongs to.
        current_event: The event that triggered this turn.
        available_agents: All loaded agents eligible to participate.
        available_skills: All loaded skills available to agents.
        event_store: The event store for snapshot reads and event appends.
        llm_router: The LLM call interface (sync, per ADR-011 D1 revised).
        regex_registry: Pre-compiled regex patterns for RegexTrigger
            evaluation (keyed by ``(agent_id, trigger_index)``).

    Returns:
        ``TurnResult`` from ``dispatch_turn``.

    Raises:
        RoomStateError: propagated unwrapped if ``next_room_state`` raises
            on an internal contract violation.
        Any exception from ``event_store.append``: propagated unwrapped
            (consistent with ADR-011 D7-b).
    """
    # 1. Snapshot (before any state_transition event is appended for this turn).
    snapshot = event_store.get_room_events(room.id)

    # 2. State machine evaluation (pure function; may raise RoomStateError).
    transition = next_room_state(room, snapshot, current_event=current_event)

    # 3. Persist state transition before dispatch so the event log reflects
    #    the transition in the order it happened.
    if transition is not None:
        transition_event = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.STATE_TRANSITION,
            author="system",
            timestamp=now_ms(),
            content="",
            metadata=StateTransitionMeta(
                prior_state=transition.prior_state,
                new_state=transition.new_state,
            ).model_dump(),
        )
        event_store.append(transition_event)

    # 4. Load-time filter: which agents enter this room_type?
    selection = decide_agents_for_room(room.type, room.state, available_agents=available_agents)

    # 5. Dispatch-time filter: which loaded agents are active in the current
    #    room_state?  Agents whose applies_to.room_states is ["*"] are always
    #    active; concrete room_states must include room.state.
    filtered: dict[str, Agent] = {
        agent.id: agent
        for agent in selection.loaded
        if agent.applies_to.room_states == ["*"] or room.state in agent.applies_to.room_states
    }

    # 6. Dispatch turn to filtered agents.
    return dispatch_turn(
        filtered,
        room,
        current_event,
        event_store=event_store,
        llm_router=llm_router,
        available_skills=available_skills,
        regex_registry=regex_registry,
    )
