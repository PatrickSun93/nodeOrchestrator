"""Wire contract for the API layer (ADR-025 D5).

Re-exports Event/Room/Snapshot raw (frozen, extra="forbid") plus the
intent/response/WS envelope shapes. Committed before any producer
(inscribe-before-producer per ADR-025 D5) so P3.3 can bind immediately.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.agents.schema import TurnResult
from orchestrator.core.event import Event, EventId, EventType
from orchestrator.core.room import Room
from orchestrator.derived.snapshot import Snapshot

__all__ = [
    "INTENT_TYPE_ALLOWLIST",
    "Event",
    "IntentError",
    "IntentRequest",
    "IntentResponse",
    "Room",
    "Snapshot",
    "StreamErrorMessage",
    "StreamEventMessage",
    "StreamMessage",
    "StreamReplayCompleteMessage",
    "TurnResult",
]

# Intent-type allowlist (ADR-025 D4a).
# UTTERANCE excluded: agent speech-act; prevents client-driven UTTERANCE-keyed transitions.
INTENT_TYPE_ALLOWLIST: frozenset[EventType] = frozenset(
    {
        EventType.USER_INPUT,
        EventType.DECISION,
        EventType.RETRACTION,
    }
)


class IntentRequest(BaseModel):
    """Client intent to append a user event and drive a turn (ADR-025 D4).

    No author/id/timestamp fields — server stamps all three. extra="forbid"
    rejects any unknown field at parse time (forge guard at schema layer).
    type must be in INTENT_TYPE_ALLOWLIST; validated at the endpoint.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: EventType
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_id: EventId | None = None


class IntentResponse(BaseModel):
    """Successful intent result: the appended user event + turn result."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    appended_event: Event
    turn: TurnResult


class IntentError(BaseModel):
    """Partial-turn error envelope (ADR-025 D5, R0-B Y3).

    stage="append": nothing persisted — safe to retry.
    stage="turn":  intent persisted — do NOT re-post; reconcile via replay.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    stage: Literal["append", "turn"]
    appended_event_id: EventId | None = None
    reason: str


class StreamEventMessage(BaseModel):
    """A live event pushed to a WS subscriber."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["event"] = "event"
    event: Event


class StreamErrorMessage(BaseModel):
    """WS-level error envelope (mirrors IntentError for client reconciliation)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["error"] = "error"
    stage: Literal["append", "turn"]
    appended_event_id: EventId | None = None
    reason: str


class StreamReplayCompleteMessage(BaseModel):
    """Sent after all replay events; client switches to live-stream mode."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["replay_complete"] = "replay_complete"


StreamMessage = Annotated[
    StreamEventMessage | StreamErrorMessage | StreamReplayCompleteMessage,
    Field(discriminator="kind"),
]
"""Discriminated WS envelope — kind field dispatches to the concrete type."""
