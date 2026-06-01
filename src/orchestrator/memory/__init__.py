"""Cross-room memory persistence — slice B + P2.4.

Public API surface for the memory package. Consumers import from here.
Internal sub-modules (store, promotion, lookup) are imported on demand
to keep this namespace explicit.

Per ADR-016: Hypothesis + VerifiedKnowledge tables + user-confirm promotion
+ cross-room lookup. Per ADR-020: Entity full surface + ProjectArchive +
user preferences (Principle-11 explicit-only via record_preference).
"""

from orchestrator.memory.archive import (
    get_project_archive,
    list_project_archives,
    record_project_archive,
)
from orchestrator.memory.entity import (
    get_entity_by_id,
    list_entities,
    list_preferences,
    record_entity,
    record_preference,
)
from orchestrator.memory.exceptions import (
    EventNotFoundError,
    HypothesisNotFoundError,
    MemoryStoreError,
    PromotionEligibilityError,
)
from orchestrator.memory.schema import (
    Entity,
    EntityId,
    EntityScope,
    EntityType,
    Hypothesis,
    HypothesisId,
    HypothesisStatus,
    ProjectArchive,
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
    "EntityScope",
    "EntityType",
    "EventNotFoundError",
    "Hypothesis",
    "HypothesisId",
    "HypothesisNotFoundError",
    "HypothesisStatus",
    "MemoryStoreError",
    "ProjectArchive",
    "PromotionEligibilityError",
    "VKId",
    "VKScope",
    "VerifiedKnowledge",
    "generate_entity_id",
    "generate_hypothesis_id",
    "generate_vk_id",
    "get_entity_by_id",
    "get_project_archive",
    "list_entities",
    "list_preferences",
    "list_project_archives",
    "record_entity",
    "record_preference",
    "record_project_archive",
]
