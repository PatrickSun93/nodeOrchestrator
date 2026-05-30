"""Pydantic models and ID generators for cross-room memory persistence.

Per ADR-016 D2: Hypothesis + VerifiedKnowledge + Entity (stub) models.
All models are frozen + extra="forbid" per the project schema-invariant pattern.

ID format:
  HypothesisId  → "hyp_<32-hex>"
  VKId          → "vk_<32-hex>"
  EntityId      → "ent_<32-hex>"
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, NewType

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.core.event import EventId, RoomId, TimestampMs

# ---------------------------------------------------------------------------
# ID NewTypes
# ---------------------------------------------------------------------------

HypothesisId = NewType("HypothesisId", str)
VKId = NewType("VKId", str)
EntityId = NewType("EntityId", str)


def generate_hypothesis_id() -> HypothesisId:
    """Format: ``hyp_<32-hex>``."""
    return HypothesisId(f"hyp_{uuid.uuid4().hex}")


def generate_vk_id() -> VKId:
    """Format: ``vk_<32-hex>``."""
    return VKId(f"vk_{uuid.uuid4().hex}")


def generate_entity_id() -> EntityId:
    """Format: ``ent_<32-hex>``."""
    return EntityId(f"ent_{uuid.uuid4().hex}")


# ---------------------------------------------------------------------------
# Status / scope enums
# ---------------------------------------------------------------------------


class HypothesisStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    STALE = "stale"


class VKScope(StrEnum):
    PERSONAL = "personal"
    TEAM = "team"
    GLOBAL = "global"


class EntityType(StrEnum):
    PERSON = "person"
    PROJECT = "project"
    CONCEPT = "concept"
    PAPER = "paper"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Hypothesis(BaseModel):
    """A candidate claim awaiting promotion to VerifiedKnowledge.

    Per ADR-016 D2. Status lifecycle: PENDING → VERIFIED | REJECTED | STALE.
    candidate_for_promotion is written by the future cross-N-rooms matcher
    (ADR-016 D7); it is False by default and is NOT a promotion precondition
    in P1.6.5.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: HypothesisId
    content: str = Field(min_length=1)
    room_id: RoomId
    confidence: float = Field(ge=0.0, le=1.0)
    source_event_ids: list[EventId] = Field(min_length=1)
    status: HypothesisStatus = HypothesisStatus.PENDING
    candidate_for_promotion: bool = False
    topic_tags: list[str] = Field(default_factory=list)
    created_at: TimestampMs


class VerifiedKnowledge(BaseModel):
    """A user-confirmed claim promoted from a Hypothesis.

    Per ADR-016 D2 + D3. Created only via promote_hypothesis(); no
    standalone constructor API in P1.6.5. contradictions lists VK IDs
    of verified claims that contradict this one (D9; no producer this cycle).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: VKId
    content: str = Field(min_length=1)
    topic_tags: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    last_validated: TimestampMs
    contradictions: list[VKId] = Field(default_factory=list)
    scope: VKScope
    promoted_from_hypothesis_id: HypothesisId
    promoted_by_user_id: str = Field(min_length=1)
    promotion_event_id: EventId


class Entity(BaseModel):
    """Schema-only stub. No producer/consumer API in P1.6.5.

    Per ADR-016 D1: ships to avoid future migration cost when an Entity
    producer/consumer surface materializes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: EntityId
    type: EntityType
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: TimestampMs
