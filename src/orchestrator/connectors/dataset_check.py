"""dataset_check: deterministic external connector (no LLM).

Validates a hypothesis against an in-memory dataset by checking for keyword
overlap between the hypothesis content and dataset keys/values. Deterministic:
same hypothesis + dataset always produces the same verdict and evidence_ref.

Calls emit_external_validation — NEVER constructs ExternalValidationMeta directly
(ADR-022 D4; c2 guard in tests/connectors/test_constitution.py enforces this).
"""

from __future__ import annotations

from orchestrator.connectors._emit import emit_external_validation
from orchestrator.core.event import EventId, RoomId
from orchestrator.core.event_store import EventStore


def check_hypothesis_against_dataset(
    hypothesis_content: str,
    dataset: dict[str, str],
    *,
    event_store: EventStore,
    room_id: RoomId,
    validated_hypothesis_id: str,
    source: str = "dataset_check",
) -> EventId | None:
    """Validate a hypothesis against a dataset of key → value entries.

    Determines verdict by checking whether any dataset key appears as a
    substring of the hypothesis content (case-insensitive). This is a
    deterministic, keyword-overlap heuristic — no LLM, no randomness.

    The matching algorithm is stable: for a given (hypothesis_content, dataset)
    pair, iteration order over the dataset dict is insertion-order (Python 3.7+
    guarantee), so the first matching key is always the same key. The function
    is therefore fully deterministic.

    Args:
        hypothesis_content: The text of the hypothesis to validate.
        dataset: Mapping of evidence keys to evidence values. The key is used
            as ``evidence_ref`` when a match is found.
        event_store: Append-only event store; passed through to emit_external_validation.
        room_id: Target room.
        validated_hypothesis_id: Must match ``^hyp_[0-9a-f]{32}$``.
        source: Identifier for this connector (default "dataset_check").

    Returns:
        EventId of the appended EXTERNAL_VALIDATION event if a match was found
        (verdict="confirmed"), or None if no match (inconclusive — no event written).
    """
    hypothesis_lower = hypothesis_content.lower()

    for key, _value in dataset.items():
        if key.lower() in hypothesis_lower:
            return emit_external_validation(
                event_store,
                room_id=room_id,
                source=source,
                verdict="confirmed",
                validated_hypothesis_id=validated_hypothesis_id,
                evidence_ref=key,
            )

    return None
