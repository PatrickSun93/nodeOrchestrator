"""Room dataclass.

Rooms are containers for events. P0 supports the basic shape: id, type,
state (placeholder for the room's state machine, defaulting to 'open'),
created_at. The agents/tools/skills lists from handoff.md §4.2 are NOT
in P0; they will be loaded from room templates in P1 once the agent
loader exists.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.core.event import RoomId, TimestampMs, now_ms


class RoomType(StrEnum):
    """Room templates. State machine and default agent/tool sets vary by
    type; those wirings come in P1."""

    FREE_CHAT = "free_chat"
    BUG_FIX = "bug_fix"
    RESEARCH = "research"
    CODE_REVIEW = "code_review"
    IDEA_VALIDATION = "idea_validation"


class Room(BaseModel):
    """A container for events.

    Append-only at the application layer (the EventStore API does not
    expose update/delete for rooms either), but the schema does not
    enforce this with TRIGGERs. Room state changes flow through
    `state_transition` events and can be derived on demand rather than
    mutating the rooms row.
    """

    id: RoomId
    type: RoomType
    state: str = "open"
    created_at: TimestampMs = Field(default_factory=now_ms)

    model_config = ConfigDict(frozen=True, extra="forbid")
