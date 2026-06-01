"""Pydantic models for the re-entry / catch-up consumer. Per ADR-021 D7.

NewSinceLeaveItem  — a typed pointer to one fact new since the leave-marker.
ReentryDigest      — the code-selected, deterministically-ordered fact-set.
ReentryResult      — digest + rendered prose (the full "AI 记得我" output).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from orchestrator.core.event import RoomId, TimestampMs
from orchestrator.memory.schema import Entity, ProjectArchive, VerifiedKnowledge


class NewSinceLeaveItem(BaseModel):
    """A code-produced pointer to one fact that appeared after the leave-marker.

    fact_type discriminates between verified knowledge and room events (D8).
    All fields are code-derived — label is event.content[:80] or VK.content[:80].
    Per ADR-021 D7/D8 (Y3 absorbed).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fact_type: Literal["verified_knowledge", "event"]
    ref_id: str
    label: str
    occurred_at: TimestampMs


class ReentryDigest(BaseModel):
    """The deterministic code-assembled catch-up fact-set.

    All selection / ordering is code (Principle 11, ADR-021 D3).
    The LLM only phrases this into prose (render_reentry_prose).
    Per ADR-021 D7.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    room_id: RoomId
    archive: ProjectArchive | None
    recalled_knowledge: list[VerifiedKnowledge]
    entities: list[Entity]
    preferences: list[Entity]
    new_since_leave: list[NewSinceLeaveItem]
    last_seen_ts: int | None
    generated_at: TimestampMs


class ReentryResult(BaseModel):
    """Full re-entry output: deterministic digest + content-gen prose render."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    digest: ReentryDigest
    prose: str
