"""Autonomy gate emission layer.

Wraps ``gate()`` and emits the appropriate audit event to the event store,
synchronously before returning or raising (ADR-005 §6, ADR-007 §3).

Layering note: this module is the **first** import edge from
``orchestrator.autonomy`` → ``orchestrator.core``. The reverse direction
(``orchestrator.core`` importing from ``orchestrator.autonomy``) remains
forbidden per the C2-freeze deliberate-duplication design documented in
``orchestrator/core/event.py:209-211``.
"""

from __future__ import annotations

from orchestrator.autonomy.scoring import (
    AutonomyScore,
    Operation,
    ThresholdConfig,
    ToolMeta,
    UnknownToolError,
    gate,
)
from orchestrator.core.event import (
    AutonomyDecisionMetadata,  # noqa: F401 — imported to trigger validate_metadata
    AutonomyRefusalMetadata,  # noqa: F401 — imported to trigger validate_metadata
    Event,
    EventType,
    RoomId,
    generate_event_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore


def emit_gate_decision(
    operation: Operation,
    tools: dict[str, ToolMeta],
    thresholds: ThresholdConfig,
    event_store: EventStore,
    *,
    room_id: RoomId,
    author: str,
) -> AutonomyScore:
    """Run the autonomy gate and emit the audit event for the outcome.

    Success path: appends ``autonomy_decision`` event with full
    ``AutonomyDecisionMetadata`` (score + tier + trace), then returns
    the ``AutonomyScore``.

    Refusal path: appends ``autonomy_refusal`` event with
    ``AutonomyRefusalMetadata`` (reason ``"unknown_tool"``), then
    re-raises ``UnknownToolError`` unwrapped (ADR-006 §3, ADR-007 §3).

    The event is always appended **before** returning or raising — this
    ordering is what makes the event the audit record of the decision,
    not a post-hoc log (ADR-005 §6, ADR-007 §3).

    Raises:
        UnknownToolError: propagated unwrapped from ``gate()`` after the
            ``autonomy_refusal`` event has been appended.
    """
    try:
        result = gate(operation, tools, thresholds)
    except UnknownToolError:
        event_store.append(
            Event(
                id=generate_event_id(),
                room_id=room_id,
                type=EventType.AUTONOMY_REFUSAL,
                author=author,
                timestamp=now_ms(),
                content=f"autonomy_refusal: {operation.tool_id!r} not in tools registry",
                metadata={
                    "operation_tool_id": operation.tool_id,
                    "operation_initiating_agent": operation.initiating_agent,
                    "user_explicit_intent": operation.user_explicit_intent,
                    "refusal_reason": "unknown_tool",
                },
            )
        )
        raise

    event_store.append(
        Event(
            id=generate_event_id(),
            room_id=room_id,
            type=EventType.AUTONOMY_DECISION,
            author=author,
            timestamp=now_ms(),
            content=f"autonomy_decision: {operation.tool_id!r} -> {result.tier}",
            metadata={
                "operation_tool_id": operation.tool_id,
                "operation_initiating_agent": operation.initiating_agent,
                "user_explicit_intent": operation.user_explicit_intent,
                "score": result.score,
                "tier": result.tier.value,
                "reversibility_score": result.trace.reversibility_score,
                "threshold_auto_raw": result.trace.threshold_auto_raw,
                "threshold_confirm_raw": result.trace.threshold_confirm_raw,
                "user_intent_modifier": result.trace.user_intent_modifier,
                "threshold_auto_effective": result.trace.threshold_auto_effective,
                "threshold_confirm_effective": result.trace.threshold_confirm_effective,
                "rule": result.trace.rule,
            },
        )
    )
    return result
