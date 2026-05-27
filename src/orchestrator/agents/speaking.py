"""Per-turn agent speaking decision.

``should_agent_speak`` implements the full ADR-010 contract:
1. No triggers → ``no_triggers_configured``.
2. Cooldown check (event-stream-driven; ms→s conversion; ADR-010 D2).
3. Trigger evaluation in list order, short-circuit on first match
   (ADR-010 D4).

Pure function: reads only from the passed ``event_stream_snapshot``
and ``current_event``; no I/O, no LLM (ADR-010 D5, ADR-011 D5).
Concurrency: §2 N/A — function is stateless.
"""

from __future__ import annotations

import re

from pydantic import ValidationError

from orchestrator.agents.exceptions import SpeakingTriggerError
from orchestrator.agents.schema import (
    Agent,
    EventTypeTrigger,
    RegexTrigger,
    SpeechDecision,
    StateChangeTrigger,
)
from orchestrator.core.event import Event, EventType, StateTransitionMeta, build_author


def should_agent_speak(
    agent: Agent,
    event_stream_snapshot: list[Event],
    *,
    current_event: Event,
    regex_registry: dict[tuple[str, int], re.Pattern[str]],
) -> SpeechDecision:
    """Decide whether ``agent`` should speak on ``current_event``.

    Implements the ADR-010 D4 evaluation order:
    1. Empty triggers → ``no_triggers_configured``.
    2. Cooldown (event-stream-driven, ms→s; ADR-010 D2).
    3. Trigger evaluation in list order; first match → ``trigger_matched``.
    4. No match → ``no_trigger_matched``.

    ``regex_registry`` must be populated by ``load_agents`` (ADR-010 D6
    revised). A missing registry entry for a ``RegexTrigger`` raises
    ``SpeakingTriggerError``.
    """
    # Step 1: no triggers configured
    if not agent.speaking_triggers:
        return SpeechDecision(
            agent_id=agent.id,
            speak=False,
            reason="no_triggers_configured",
        )

    # Step 2: cooldown check (ADR-010 D2)
    #
    # Find the most recent UTTERANCE event in the snapshot authored by
    # this agent.  Use build_author() — single point of format truth;
    # defense-in-depth against silent cooldown bypass on malformed
    # author strings (DeepSeek R0-B 🟡#6).
    author = build_author(agent.id)
    last_utterance: Event | None = None
    for ev in reversed(event_stream_snapshot):
        if ev.type == EventType.UTTERANCE and ev.author == author:
            last_utterance = ev
            break

    if last_utterance is not None and agent.cooldown_seconds > 0:
        # Explicit unit conversion site (ADR-010 D2 revised, R0-B 🔴#1):
        # event.timestamp is milliseconds; cooldown_seconds is seconds.
        elapsed_s = (current_event.timestamp - last_utterance.timestamp) / 1000.0
        if elapsed_s < agent.cooldown_seconds:
            cooldown_remaining_s = float(agent.cooldown_seconds) - elapsed_s
            return SpeechDecision(
                agent_id=agent.id,
                speak=False,
                reason="cooldown_active",
                cooldown_remaining_s=cooldown_remaining_s,
            )

    # Step 3: trigger evaluation in list order (ADR-010 D4)
    for i, trigger in enumerate(agent.speaking_triggers):
        if isinstance(trigger, RegexTrigger):
            pattern = regex_registry.get((agent.id, i))
            if pattern is None:
                raise SpeakingTriggerError(
                    f"agent {agent.id!r}: regex_registry missing key "
                    f"({agent.id!r}, {i}) — ensure load_agents populated the registry",
                    agent_id=agent.id,
                    trigger_index=i,
                )
            if pattern.search(current_event.content):
                return SpeechDecision(
                    agent_id=agent.id,
                    speak=True,
                    reason="trigger_matched",
                    matched_trigger_index=i,
                )

        elif isinstance(trigger, EventTypeTrigger):
            if current_event.type == trigger.event_type:
                return SpeechDecision(
                    agent_id=agent.id,
                    speak=True,
                    reason="trigger_matched",
                    matched_trigger_index=i,
                )

        elif isinstance(trigger, StateChangeTrigger):
            if current_event.type == EventType.STATE_TRANSITION:
                # Typed metadata access per ADR-010 D1 + ADR-011 D5 (R0-B 🔴#2).
                # NOT dict access: current_event.metadata["new_state"] would
                # silently pass on malformed events; typed access raises on
                # schema violations.
                try:
                    meta = StateTransitionMeta.model_validate(current_event.metadata)
                except ValidationError:
                    continue
                if meta.new_state == trigger.target_state:
                    return SpeechDecision(
                        agent_id=agent.id,
                        speak=True,
                        reason="trigger_matched",
                        matched_trigger_index=i,
                    )

    # Step 4: no trigger matched
    return SpeechDecision(
        agent_id=agent.id,
        speak=False,
        reason="no_trigger_matched",
    )
