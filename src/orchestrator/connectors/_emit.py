"""emit_external_validation: the SOLE construction site for ExternalValidationMeta.

ADR-022 D4: external connectors MUST call this helper rather than constructing
ExternalValidationMeta directly. This ensures ``evidence_ref`` is required and
non-empty at the connector contract layer (the schema allows None for forward
compatibility, but real connector calls must supply a grounding reference).

NEVER raw-INSERT into the events table — only ``event_store.append()``.
"""

from __future__ import annotations

from typing import Literal

from orchestrator.core.event import (
    Event,
    EventId,
    EventType,
    ExternalValidationMeta,
    RoomId,
    generate_event_id,
    now_ms,
    validate_metadata,
)
from orchestrator.core.event_store import EventStore


def emit_external_validation(
    event_store: EventStore,
    *,
    room_id: RoomId,
    source: str,
    verdict: Literal["confirmed", "refuted", "inconclusive"],
    validated_hypothesis_id: str,
    evidence_ref: str,
) -> EventId:
    """Append an EXTERNAL_VALIDATION event to the event store.

    This is the sole construction site for ExternalValidationMeta in
    non-test source code (c2 guard in tests/connectors/test_constitution.py).

    Args:
        event_store: Append-only event store (append() only — no raw SQL).
        room_id: Target room.
        source: Identifier of the external system producing this validation.
        verdict: One of "confirmed", "refuted", "inconclusive".
        validated_hypothesis_id: Must match ``^hyp_[0-9a-f]{32}$``.
        evidence_ref: Non-empty reference to the evidence grounding this verdict.
            The connector contract (not the schema) requires this to be non-empty —
            a validation event without an evidence reference is ungrounded and
            therefore meaningless for the memory layer.

    Returns:
        The EventId of the appended event.

    Raises:
        ValueError: If ``evidence_ref`` is empty or falsy.
        MetadataValidationError: If metadata fails the ExternalValidationMeta schema.
        RoomNotFoundError: If ``room_id`` does not exist in the store.
    """
    if not evidence_ref:
        raise ValueError(
            "evidence_ref is required and must be non-empty for external validation events. "
            "A validation without an evidence reference is ungrounded."
        )

    meta = ExternalValidationMeta(
        source=source,
        verdict=verdict,
        validated_hypothesis_id=validated_hypothesis_id,
        evidence_ref=evidence_ref,
    )
    metadata_dict = validate_metadata(EventType.EXTERNAL_VALIDATION, meta.model_dump())

    event = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.EXTERNAL_VALIDATION,
        author="system",
        timestamp=now_ms(),
        content=f"external_validation: {verdict} for {validated_hypothesis_id} via {source}",
        metadata=metadata_dict,
    )
    return event_store.append(event)
