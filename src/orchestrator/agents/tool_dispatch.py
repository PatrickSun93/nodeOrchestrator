"""Autonomy-aware tool-call dispatch for agent responses.

Processes LLMResponse.tool_calls after dispatch_turn captures an LLM
response. For each ToolCall: builds an Operation, calls emit_gate_decision,
and for AUTO_EXECUTE tier only, appends a tool_call event. See ADR-013.

Layering: imports from autonomy/emission, core/event, agents/schema only.
No LLM imports — tool_calls arrive pre-parsed as ToolCall instances.
"""

from __future__ import annotations

import logging
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from orchestrator.autonomy.emission import emit_gate_decision
from orchestrator.autonomy.scoring import (
    AutonomyTier,
    Operation,
    ThresholdConfig,
    ToolMeta,
    UnknownToolError,
)
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    ToolCallMeta,
    ToolCallPendingMeta,
    build_author,
    generate_event_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.llm.types import ToolCall

_log = logging.getLogger("orchestrator.agents.tool_dispatch")


class ToolDispatchDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str
    tool_name: str
    tier: AutonomyTier | None  # None when UnknownToolError raised
    tool_call_event_appended: bool  # True only when tier == AUTO_EXECUTE
    refusal_reason: Literal["unknown_tool"] | None


class ToolDispatchResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decisions: list[ToolDispatchDecision]  # one per processed tool_call


def process_tool_calls(
    tool_calls: list[ToolCall],
    *,
    agent_id: str,
    room_id: RoomId,
    current_event: Event,
    event_store: EventStore,
    tools: dict[str, ToolMeta],
    thresholds: ThresholdConfig,
) -> ToolDispatchResult:
    """For each tool call: build Operation, call emit_gate_decision,
    and for AUTO_EXECUTE only, append a tool_call event. See ADR-013."""
    decisions: list[ToolDispatchDecision] = []
    user_explicit_intent = current_event.type == EventType.USER_INPUT  # ADR-013 D3

    for tc in tool_calls:
        operation = Operation(
            tool_id=tc.name,
            initiating_agent=agent_id,
            user_explicit_intent=user_explicit_intent,
            params=tc.arguments,
        )
        try:
            result = emit_gate_decision(
                operation,
                tools,
                thresholds,
                event_store,
                room_id=room_id,
                author=build_author(agent_id),
            )
        except UnknownToolError:
            decisions.append(
                ToolDispatchDecision(
                    call_id=tc.id,
                    tool_name=tc.name,
                    tier=None,
                    tool_call_event_appended=False,
                    refusal_reason="unknown_tool",
                )
            )
            continue

        if result.tier == AutonomyTier.AUTO_EXECUTE:
            event_store.append(
                Event(
                    id=generate_event_id(),
                    room_id=room_id,
                    type=EventType.TOOL_CALL,
                    author=build_author(agent_id),
                    timestamp=now_ms(),
                    content="",
                    metadata=ToolCallMeta(
                        tool_name=tc.name,
                        call_id=tc.id,
                        params=tc.arguments,
                    ).model_dump(),
                )
            )
            decisions.append(
                ToolDispatchDecision(
                    call_id=tc.id,
                    tool_name=tc.name,
                    tier=result.tier,
                    tool_call_event_appended=True,
                    refusal_reason=None,
                )
            )
        else:
            # COUNTDOWN_CONFIRM / HARD_CONFIRM: persist the full payload so
            # the confirm endpoint can reconstruct and execute it (ADR-030 D1).
            event_store.append(
                Event(
                    id=generate_event_id(),
                    room_id=room_id,
                    type=EventType.TOOL_CALL_PENDING,
                    author=build_author(agent_id),
                    timestamp=now_ms(),
                    content="",
                    metadata=ToolCallPendingMeta(
                        tool_name=tc.name,
                        call_id=tc.id,
                        params=tc.arguments,
                        tier=cast(Literal["countdown_confirm", "hard_confirm"], result.tier.value),
                        initiating_agent=agent_id,
                    ).model_dump(),
                )
            )
            decisions.append(
                ToolDispatchDecision(
                    call_id=tc.id,
                    tool_name=tc.name,
                    tier=result.tier,
                    tool_call_event_appended=False,
                    refusal_reason=None,
                )
            )

    _log.info(
        "tool_dispatch: agent=%s processed=%d decisions=%s",
        agent_id,
        len(decisions),
        [(d.tool_name, d.tier) for d in decisions],
    )
    return ToolDispatchResult(decisions=decisions)
