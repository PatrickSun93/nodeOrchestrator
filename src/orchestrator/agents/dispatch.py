"""Multi-agent turn-dispatch primitive.

``dispatch_turn`` implements the ADR-011 sequential dispatch contract:
1. Snapshot taken once at turn entry (ADR-011 D2).
2. Agents evaluated in alphabetical-id order (ADR-011 D3 revised).
3. Per-agent: should_agent_speak → build_agent_context → llm_router.call → append.
4. LLM exception: log + skip + continue (ADR-011 D7).
5. event_store.append exception: propagate unwrapped (ADR-011 D7-b).

Sync ``def`` per ADR-011 D1 revised (no async color in P1.4;
P1.5+ re-shapes both signature and body for concurrent dispatch).
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

from orchestrator.agents.schema import Agent, TurnResult
from orchestrator.agents.selection import build_agent_context
from orchestrator.agents.speaking import should_agent_speak
from orchestrator.core.event import (
    Event,
    EventType,
    build_author,
    generate_event_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import LLMRequest, LLMResponse, Message, generate_request_id
from orchestrator.skills.schema import Skill

_log = logging.getLogger("orchestrator.agents.dispatch")


class LLMRouterProtocol(Protocol):
    """Synchronous LLM call interface consumed by ``dispatch_turn``.

    P1.5+ re-shapes this to ``async def`` when concurrent dispatch lands.
    Implementations wrap routing (model/provider selection) + provider call.
    """

    def call(self, request: LLMRequest) -> LLMResponse: ...


def dispatch_turn(
    agents: dict[str, Agent],
    room: Room,
    current_event: Event,
    *,
    event_store: EventStore,
    llm_router: LLMRouterProtocol,
    available_skills: dict[str, Skill],
    regex_registry: dict[tuple[str, int], re.Pattern[str]],
) -> TurnResult:
    """Dispatch one turn to all eligible agents, sequentially.

    Snapshot is taken once at function entry and held fixed for the
    entire turn (ADR-011 D2). Agents are evaluated in ascending
    alphabetical id order (ADR-011 D3 revised). LLM failures are
    logged and skipped; event-store failures abort the turn (D7/D7-b).

    Returns:
        TurnResult with utterances appended, failed_agents ids, and
        total_asked count (speak=True agents regardless of LLM outcome).
    """
    snapshot = event_store.get_room_events(room.id)
    sorted_agents = sorted(agents.values(), key=lambda a: a.id)

    utterances: list[Event] = []
    failed_agents: list[str] = []
    total_asked = 0

    for agent in sorted_agents:
        decision = should_agent_speak(
            agent,
            snapshot,
            current_event=current_event,
            regex_registry=regex_registry,
        )
        if not decision.speak:
            continue

        total_asked += 1
        context = build_agent_context(
            agent,
            room.type,
            room.state,
            available_skills=available_skills,
            snapshot=snapshot,
        )

        system_parts = [agent.persona, *context.skill_bodies]
        system = "\n\n".join(p for p in system_parts if p) or None
        request = LLMRequest(
            request_id=generate_request_id(),
            purpose=LLMPurpose.AGENT_RESPONSE,
            caller_agent_id=agent.id,
            system=system,
            messages=[Message(role="user", content=current_event.content or " ")],
        )

        try:
            response = llm_router.call(request)
        except Exception as exc:
            _log.warning(
                "agent %s LLM call failed; skipping turn (continuing): %s",
                agent.id,
                exc,
            )
            failed_agents.append(agent.id)
            continue

        utterance = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.UTTERANCE,
            author=build_author(agent.id),
            timestamp=now_ms(),
            content=response.content,
            parent_id=current_event.id,
        )
        event_store.append(utterance)  # propagates unwrapped per ADR-011 D7-b
        utterances.append(utterance)

    return TurnResult(
        utterances=utterances,
        failed_agents=failed_agents,
        total_asked=total_asked,
    )
