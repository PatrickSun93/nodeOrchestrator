"""Cross-room memory persistence — slice B.

Public API surface for the memory package. Consumers import from here.
Internal sub-modules (store, promotion, lookup) are imported on demand
to keep this namespace explicit.

Per ADR-016: Hypothesis + VerifiedKnowledge tables + user-confirm promotion
+ cross-room lookup. Entity ships as schema-only stub. ProjectArchive deferred.
"""

from orchestrator.memory.exceptions import (
    EventNotFoundError,
    HypothesisNotFoundError,
    MemoryStoreError,
    PromotionEligibilityError,
)
from orchestrator.memory.schema import (
    Entity,
    EntityId,
    EntityType,
    Hypothesis,
    HypothesisId,
    HypothesisStatus,
    VerifiedKnowledge,
    VKId,
    VKScope,
    generate_entity_id,
    generate_hypothesis_id,
    generate_vk_id,
)

__all__ = [
    "Entity",
    "EntityId",
    "EntityType",
    "EventNotFoundError",
    "Hypothesis",
    "HypothesisId",
    "HypothesisNotFoundError",
    "HypothesisStatus",
    "MemoryStoreError",
    "PromotionEligibilityError",
    "VKId",
    "VKScope",
    "VerifiedKnowledge",
    "generate_entity_id",
    "generate_hypothesis_id",
    "generate_vk_id",
]
