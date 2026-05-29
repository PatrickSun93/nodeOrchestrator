"""Error classes for the memory package.

Per ADR-016 D2 + plan P1.6.5-1:
  - HypothesisNotFoundError: raised when a hyp_id does not reference any row.
  - EventNotFoundError: raised by record_hypothesis when any source_event_id
    is absent from the event store (Y2 alpha-(ii) routing).
  - PromotionEligibilityError: raised by promote_hypothesis when
    hypothesis.status != PENDING.
  - MemoryStoreError: general SQLite-level failure from memory operations.
"""

from __future__ import annotations


class HypothesisNotFoundError(LookupError):
    """No Hypothesis row found for the given hyp_id."""

    def __init__(self, hyp_id: str) -> None:
        self.hyp_id = hyp_id
        super().__init__(f"hypothesis {hyp_id!r} not found")


class EventNotFoundError(LookupError):
    """A source_event_id passed to record_hypothesis does not exist in
    the event store.

    Per ADR-016 D2 line 155: record_hypothesis enforces producer-time
    existence of all source_event_ids. Missing event raises this error
    before any INSERT occurs.
    """

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(f"source event {event_id!r} not found in event store")


class PromotionEligibilityError(ValueError):
    """Hypothesis is not eligible for promotion (status != PENDING).

    Per ADR-016 D3: only PENDING hypotheses may be promoted.
    """

    def __init__(self, hyp_id: str, reason: str) -> None:
        self.hyp_id = hyp_id
        self.reason = reason
        super().__init__(f"hypothesis {hyp_id!r} not eligible for promotion: {reason}")


class MemoryStoreError(RuntimeError):
    """General failure from a memory-store SQLite operation."""
