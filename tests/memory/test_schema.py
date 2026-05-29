"""Tests for memory/schema.py — §6 schema invariants + ID generators + enums.

Per docs/process/test-coverage-standard.md §6: frozen + extra="forbid" +
required-field-absent + wrong-type. Minimum 12 §6 tests across the 3 models.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.core.event import (
    TimestampMs,
    generate_event_id,
    generate_room_id,
)
from orchestrator.memory.schema import (
    Entity,
    EntityType,
    Hypothesis,
    HypothesisStatus,
    VerifiedKnowledge,
    VKScope,
    generate_entity_id,
    generate_hypothesis_id,
    generate_vk_id,
)

# ---------------------------------------------------------------------------
# ID generator tests
# ---------------------------------------------------------------------------


def test_generate_hypothesis_id_prefix() -> None:
    hid = generate_hypothesis_id()
    assert hid.startswith("hyp_"), f"expected hyp_ prefix, got: {hid!r}"
    assert len(hid) == 36  # "hyp_" (4) + 32 hex chars


def test_generate_vk_id_prefix() -> None:
    vid = generate_vk_id()
    assert vid.startswith("vk_"), f"expected vk_ prefix, got: {vid!r}"
    assert len(vid) == 35  # "vk_" (3) + 32 hex chars


def test_generate_entity_id_prefix() -> None:
    eid = generate_entity_id()
    assert eid.startswith("ent_"), f"expected ent_ prefix, got: {eid!r}"
    assert len(eid) == 36  # "ent_" (4) + 32 hex chars


def test_id_generators_unique() -> None:
    ids = {generate_hypothesis_id() for _ in range(10)}
    assert len(ids) == 10


# ---------------------------------------------------------------------------
# Enum round-trip tests
# ---------------------------------------------------------------------------


def test_hypothesis_status_enum_values() -> None:
    assert HypothesisStatus.PENDING.value == "pending"
    assert HypothesisStatus.VERIFIED.value == "verified"
    assert HypothesisStatus.REJECTED.value == "rejected"
    assert HypothesisStatus.STALE.value == "stale"


def test_vk_scope_enum_values() -> None:
    assert VKScope.PERSONAL.value == "personal"
    assert VKScope.TEAM.value == "team"
    assert VKScope.GLOBAL.value == "global"


def test_entity_type_enum_values() -> None:
    assert EntityType.PERSON.value == "person"
    assert EntityType.PROJECT.value == "project"
    assert EntityType.CONCEPT.value == "concept"
    assert EntityType.PAPER.value == "paper"


# ---------------------------------------------------------------------------
# Hypothesis model — §6 schema invariants
# ---------------------------------------------------------------------------


def _make_hypothesis(**overrides: object) -> Hypothesis:
    defaults: dict[str, object] = {
        "id": generate_hypothesis_id(),
        "content": "The sky is blue.",
        "room_id": generate_room_id(),
        "confidence": 0.8,
        "source_event_ids": [generate_event_id()],
        "created_at": TimestampMs(1_700_000_000_000),
    }
    defaults.update(overrides)
    return Hypothesis(**defaults)  # type: ignore[arg-type]


def test_hypothesis_valid_construction() -> None:
    h = _make_hypothesis()
    assert h.status == HypothesisStatus.PENDING
    assert h.candidate_for_promotion is False


def test_hypothesis_frozen() -> None:
    h = _make_hypothesis()
    with pytest.raises(ValidationError):
        h.content = "mutated"

def test_hypothesis_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        Hypothesis(  # type: ignore[call-arg]
            id=generate_hypothesis_id(),
            content="x",
            room_id=generate_room_id(),
            confidence=0.5,
            source_event_ids=[generate_event_id()],
            created_at=TimestampMs(1_700_000_000_000),
            unexpected_field="value",
        )


def test_hypothesis_required_field_absent() -> None:
    with pytest.raises(ValidationError):
        Hypothesis(  # type: ignore[call-arg]
            id=generate_hypothesis_id(),
            content="x",
            room_id=generate_room_id(),
            # confidence missing
            source_event_ids=[generate_event_id()],
            created_at=TimestampMs(1_700_000_000_000),
        )


def test_hypothesis_confidence_out_of_range() -> None:
    with pytest.raises(ValidationError):
        _make_hypothesis(confidence=1.5)
    with pytest.raises(ValidationError):
        _make_hypothesis(confidence=-0.1)


def test_hypothesis_confidence_boundary_values() -> None:
    h_low = _make_hypothesis(confidence=0.0)
    assert h_low.confidence == 0.0
    h_high = _make_hypothesis(confidence=1.0)
    assert h_high.confidence == 1.0


def test_hypothesis_source_event_ids_min_length() -> None:
    with pytest.raises(ValidationError):
        _make_hypothesis(source_event_ids=[])


def test_hypothesis_empty_content_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_hypothesis(content="")


def test_hypothesis_wrong_type_for_confidence() -> None:
    with pytest.raises(ValidationError):
        _make_hypothesis(confidence="not-a-float")


# ---------------------------------------------------------------------------
# VerifiedKnowledge model — §6 schema invariants
# ---------------------------------------------------------------------------


def _make_vk(**overrides: object) -> VerifiedKnowledge:
    defaults: dict[str, object] = {
        "id": generate_vk_id(),
        "content": "Water boils at 100°C at sea level.",
        "scope": VKScope.PERSONAL,
        "last_validated": TimestampMs(1_700_000_000_000),
        "promoted_from_hypothesis_id": generate_hypothesis_id(),
        "promoted_by_user_id": "peidong",
        "promotion_event_id": generate_event_id(),
    }
    defaults.update(overrides)
    return VerifiedKnowledge(**defaults)  # type: ignore[arg-type]


def test_vk_valid_construction() -> None:
    vk = _make_vk()
    assert vk.topic_tags == []
    assert vk.evidence == {}
    assert vk.contradictions == []


def test_vk_frozen() -> None:
    vk = _make_vk()
    with pytest.raises(ValidationError):
        vk.content = "mutated"

def test_vk_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        VerifiedKnowledge(  # type: ignore[call-arg]
            id=generate_vk_id(),
            content="x",
            scope=VKScope.TEAM,
            last_validated=TimestampMs(1_700_000_000_000),
            promoted_from_hypothesis_id=generate_hypothesis_id(),
            promoted_by_user_id="u",
            promotion_event_id=generate_event_id(),
            surprise_field="boom",
        )


def test_vk_required_field_absent() -> None:
    with pytest.raises(ValidationError):
        VerifiedKnowledge(  # type: ignore[call-arg]
            id=generate_vk_id(),
            content="x",
            # scope missing
            last_validated=TimestampMs(1_700_000_000_000),
            promoted_from_hypothesis_id=generate_hypothesis_id(),
            promoted_by_user_id="u",
            promotion_event_id=generate_event_id(),
        )


def test_vk_empty_content_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_vk(content="")


def test_vk_empty_user_id_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_vk(promoted_by_user_id="")


# ---------------------------------------------------------------------------
# Entity model — §6 schema invariants
# ---------------------------------------------------------------------------


def _make_entity(**overrides: object) -> Entity:
    defaults: dict[str, object] = {
        "id": generate_entity_id(),
        "type": EntityType.CONCEPT,
        "created_at": TimestampMs(1_700_000_000_000),
    }
    defaults.update(overrides)
    return Entity(**defaults)  # type: ignore[arg-type]


def test_entity_valid_construction() -> None:
    e = _make_entity()
    assert e.attributes == {}


def test_entity_frozen() -> None:
    e = _make_entity()
    with pytest.raises(ValidationError):
        e.type = EntityType.PERSON

def test_entity_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        Entity(  # type: ignore[call-arg]
            id=generate_entity_id(),
            type=EntityType.PERSON,
            created_at=TimestampMs(1_700_000_000_000),
            nope="bad",
        )


def test_entity_required_field_absent() -> None:
    with pytest.raises(ValidationError):
        Entity(  # type: ignore[call-arg]
            id=generate_entity_id(),
            # type missing
            created_at=TimestampMs(1_700_000_000_000),
        )


# ---------------------------------------------------------------------------
# Exception isinstance tests (§4 exception payloads)
# ---------------------------------------------------------------------------


def test_exception_classes_inherit_correctly() -> None:
    from orchestrator.memory.exceptions import (
        EventNotFoundError,
        HypothesisNotFoundError,
        MemoryStoreError,
        PromotionEligibilityError,
    )

    assert isinstance(HypothesisNotFoundError("hyp_x"), LookupError)
    assert isinstance(EventNotFoundError("evt_x"), LookupError)
    assert isinstance(PromotionEligibilityError("hyp_x", "not_pending"), ValueError)
    assert isinstance(MemoryStoreError("oops"), RuntimeError)
