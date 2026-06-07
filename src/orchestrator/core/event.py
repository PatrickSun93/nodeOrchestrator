"""Core event types: Event, EventType, metadata schemas, Relation, exceptions.

This file defines the SHAPE of events in the system. It contains no SQL,
no I/O, no decision logic beyond per-type metadata validation (which is a
parser, not a routing decision). All routing, gating, and persistence
lives in event_store.py.

Per the architecture rules in handoff.md and chat-history.md:
  - Decision paths in code (event_store.py).
  - Type definitions and pure parsing (this file).
  - LLM content generation (not in this file).
"""

from __future__ import annotations

import re
import time
import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal, NewType

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

# ---------------------------------------------------------------------------
# Identifier and timestamp newtypes
# ---------------------------------------------------------------------------

EventId = NewType("EventId", str)
RoomId = NewType("RoomId", str)
TimestampMs = NewType("TimestampMs", int)


def now_ms() -> TimestampMs:
    """Current wall-clock time in epoch milliseconds."""
    return TimestampMs(int(time.time() * 1000))


def generate_event_id() -> EventId:
    """Generate a new event id.

    Format: ``evt_<32-hex>`` (Stripe-style typed prefix + uuid4 hex).
    The prefix lets a human reading logs distinguish events from rooms or
    other entities at a glance — debugging is the first audience for ids.
    Chronological ordering is the responsibility of the ``timestamp``
    column, not the id, so uuid4's lack of time-sortability is irrelevant.

    If we later want time-sortable ids (uuid7), the format can change
    without affecting any external API: callers always treat ids as
    opaque strings.
    """
    return EventId(f"evt_{uuid.uuid4().hex}")


def generate_room_id() -> RoomId:
    """Generate a new room id.

    Format: ``room_<32-hex>``. Same Stripe-style typed-prefix logic as
    ``generate_event_id`` — the prefix is for human readers, not parsers.
    """
    return RoomId(f"room_{uuid.uuid4().hex}")


# ---------------------------------------------------------------------------
# Event types — the system's vocabulary
# ---------------------------------------------------------------------------


class EventType(StrEnum):
    """The constitutional event types (ADR-030 adds TOOL_CALL_PENDING + TOOL_CALL_CANCELLED).

    See docs/architecture/event-model.md for why this list is constitutional
    and what to do (and not do) when extending it. In short: adding a type
    requires an ADR; renaming or merging types is a breaking change; a
    `generic_message` catch-all is forbidden.
    """

    USER_INPUT = "user_input"
    UTTERANCE = "utterance"
    HYPOTHESIS = "hypothesis"
    DECISION = "decision"
    REJECTION = "rejection"
    RETRACTION = "retraction"
    OBSERVATION = "observation"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_FAILED = "tool_failed"
    ESCALATION = "escalation"
    SUMMARY_SNAPSHOT = "summary_snapshot"
    STATE_TRANSITION = "state_transition"
    MILESTONE = "milestone"
    TERM_DEFINITION = "term_definition"
    DECISION_PIVOT = "decision_pivot"
    AUTONOMY_DECISION = "autonomy_decision"
    AUTONOMY_REFUSAL = "autonomy_refusal"
    EXTERNAL_VALIDATION = "external_validation"
    # ADR-030: confirm-then-execute gating-approval records
    TOOL_CALL_PENDING = "tool_call_pending"
    TOOL_CALL_CANCELLED = "tool_call_cancelled"


class RelationType(StrEnum):
    """Structural relation types extracted from events.

    These are the four edges that can be derived purely from event metadata
    (no LLM interpretation). Semantic relations (`supersedes`, `derives_from`,
    `related_to`) require LLM-suggested + human-confirmed flow; out of P0.
    """

    REJECTS = "rejects"
    RETRACTS = "retracts"
    BASED_ON = "based_on"
    REPLIES_TO = "replies_to"


# ---------------------------------------------------------------------------
# Per-type metadata schemas
#
# Strict schema for the ~6 types code reliably writes/reads in P0.
# Other 10 types pass through as dict[str, Any] until a use case
# justifies tightening (with an ADR).
# ---------------------------------------------------------------------------


class _BaseMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HypothesisMeta(_BaseMeta):
    """Metadata for `hypothesis` events.

    `confidence` is required and bounded. `based_on` may be empty for
    fresh hypotheses with no prior anchoring event.
    """

    confidence: float = Field(ge=0.0, le=1.0)
    based_on: list[EventId] = Field(default_factory=list)


class DecisionMeta(_BaseMeta):
    """Metadata for `decision` events.

    `based_on` must list at least one event the decision rests on; a
    decision without a citation is a gut call and should be appended as
    an `utterance` instead. `trade_offs` is a free-form mapping of
    dimension -> choice (e.g., `"cost": "accepted higher to reduce risk"`).

    P1.6.5 / ADR-016 D8: four optional fields for promotion-flavored decisions.
    hypothesis_id + vk_id are `str | None` (not HypothesisId | VKId) per
    deliberate-duplication (ADR-014 D5 precedent): core/event.py MUST NOT
    import from memory/schema.py. Field(pattern=...) enforces id-prefix shape
    (proxy Y5 / external Y5 → alpha-(a)). user_id records the confirming user
    of a (b) user-confirm promotion so the canonical event is self-describing
    for an event-stream-only audit (impl-stage Y2 → alpha-(a)); author stays
    `system` (the subsystem executed the write); user_id is who confirmed it.
    """

    based_on: list[EventId] = Field(min_length=1)
    trade_offs: dict[str, str] = Field(default_factory=dict)
    promotion: bool = False
    hypothesis_id: Annotated[str, Field(pattern=r"^hyp_[0-9a-f]{32}$")] | None = None
    vk_id: Annotated[str, Field(pattern=r"^vk_[0-9a-f]{32}$")] | None = None
    user_id: Annotated[str, Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def _promotion_co_presence(self) -> DecisionMeta:
        # Co-presence (impl-stage Y2): user_id joins hypothesis_id + vk_id as a
        # promotion-required field — every (b) user-confirm promotion has a
        # confirming user, so the canonical decision event must record it.
        if self.promotion and (
            self.hypothesis_id is None or self.vk_id is None or self.user_id is None
        ):
            raise ValueError("promotion=True requires hypothesis_id, vk_id, and user_id")
        if not self.promotion and (
            self.hypothesis_id is not None or self.vk_id is not None or self.user_id is not None
        ):
            raise ValueError("hypothesis_id/vk_id/user_id forbidden when promotion=False")
        return self


class RejectionMeta(_BaseMeta):
    """Metadata for `rejection` events.

    A rejection must cite the specific event it rejects (per the skeptic's
    forbidden_behaviors in chat-history.md §3 — "vague rejection" is a
    forbidden behavior).
    """

    rejects: EventId
    reason: str = Field(min_length=1)


class RetractionMeta(_BaseMeta):
    """Metadata for `retraction` events.

    The original event is NOT removed; the retraction is an additive
    event that supersedes it. `retracts` cites the prior event.
    """

    retracts: EventId
    reason: str = Field(min_length=1)


class ToolCallMeta(_BaseMeta):
    """Metadata for `tool_call` events.

    `call_id` ties this call to its eventual `tool_result` or
    `tool_failed` event for replay and audit.

    `approver_user_id` records the authenticated approver (ADR-039 D6,
    P4.5-5). Nullable for backward-compat: pre-P4.5 events have no approver.
    The still-pending scan never inspects this field — it keys on type+call_id.
    The executed TOOL_CALL stays agent-authored; this field records who approved.
    """

    tool_name: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    approver_user_id: str | None = None


class ToolResultMeta(_BaseMeta):
    """Metadata for `tool_result` events.

    `output_truncated_at` records the byte offset where the tool result
    was cut for context window reasons (None if the result was returned
    in full). `error_class` is set if the tool returned a recoverable
    error inline rather than via a separate `tool_failed` event.
    """

    call_id: str = Field(min_length=1)
    success: bool
    output_truncated_at: int | None = None
    error_class: str | None = None


class AutonomyDecisionMetadata(_BaseMeta):
    """Metadata for `autonomy_decision` events.

    Carries the full decision trace for every autonomy gate evaluation.
    Emitted synchronously before tool execution proceeds; this ordering
    is what makes the event the audit record of the decision. See
    ADR-005 Decision 6.

    Field set is locked by the constitutional test
    `test_constitution_autonomy_decision_event_carries_trace`. The
    shape mirrors `DecisionTrace` from `orchestrator.autonomy.scoring`
    with `tool_id` renamed to `operation_tool_id` and two event-only
    additions (`operation_initiating_agent`, `score`). The duplication
    is deliberate — `orchestrator.core` must not import from
    `orchestrator.autonomy` to preserve layering.
    """

    operation_tool_id: str
    operation_initiating_agent: str
    user_explicit_intent: bool
    score: int  # 0..10
    tier: Literal[
        "auto_execute",
        "countdown_confirm",
        "hard_confirm",
    ]
    reversibility_score: int
    threshold_auto_raw: int
    threshold_confirm_raw: int
    user_intent_modifier: int
    threshold_auto_effective: int
    threshold_confirm_effective: int
    rule: Literal[
        "score_ge_auto",
        "score_between_confirm_and_auto",
        "score_lt_confirm",
    ]


class AutonomyRefusalMetadata(_BaseMeta):
    """Metadata for ``autonomy_refusal`` events.

    Written by the autonomy emission layer when ``gate()`` raises before
    returning an ``AutonomyScore``. The field set is deliberately lighter
    than ``AutonomyDecisionMetadata`` — there was no decision to trace.
    See ADR-007 Decision 2.

    ``refusal_reason`` is a discriminator for future refusal classes
    (P1.3 Hard Guards will extend the Literal via ADR amendment). P1.2
    writes only ``"unknown_tool"``.

    Field set is locked by the constitutional test
    ``test_constitution_autonomy_refusal_metadata_field_set``.
    """

    operation_tool_id: str
    operation_initiating_agent: str
    user_explicit_intent: bool
    refusal_reason: Literal["unknown_tool"]


class StateTransitionMeta(_BaseMeta):
    """Metadata for ``state_transition`` events.

    Carries both endpoints of the state-machine arc. ``prior_state``
    was added in P1.5 — the first real producer of ``state_transition``
    events (ADR-012 D6). Required by ``StateChangeTrigger`` evaluation
    in ``should_agent_speak`` (ADR-010 D1, ADR-011 D5 R0-B 🔴#2).
    """

    new_state: str = Field(min_length=1)
    prior_state: str = Field(min_length=1)


class SummarySnapshotMeta(_BaseMeta):
    """Metadata for ``summary_snapshot`` events.

    Field shape mirrors ``Snapshot`` (deliberate duplication — ``orchestrator.core``
    MUST NOT import from ``orchestrator.derived`` per layering; same pattern as
    ``AutonomyDecisionMetadata`` at line 198+ mirroring ``DecisionTrace`` from
    ``autonomy/scoring.py``). See ADR-014 D5 for the duplication rationale.
    """

    room_id: str
    room_type: str
    room_state: str
    snapshot_at: int
    event_count: int = Field(ge=0)
    decision_count: int = Field(ge=0)
    open_hypotheses: list[dict[str, str]]  # serialized HypothesisRef
    closed_decisions: list[dict[str, str]]  # serialized DecisionRef
    tool_calls_pending_confirm: list[dict[str, Any]]
    last_state_transition: dict[str, Any] | None
    participants: list[str]


class ExternalValidationMeta(_BaseMeta):
    """Metadata for ``external_validation`` events (ADR-019 D1).

    Written by external connectors (CI hooks, paper-DB lookups, benchmark
    runners, etc.) via ``event_store.append``. ``memory/`` reads the typed
    verdict as a pure-code predicate — no LLM judgment inside ``memory/``.

    ``validated_hypothesis_id`` is a pattern-validated ``str``, NOT a
    ``HypothesisId`` import — deliberate-duplication (``core/`` MUST NOT
    import from ``memory/``; mirrors ``DecisionMeta.hypothesis_id`` at line
    156 in this file).
    """

    source: str = Field(min_length=1)
    verdict: Literal["confirmed", "refuted", "inconclusive"]
    validated_hypothesis_id: Annotated[str, Field(pattern=r"^hyp_[0-9a-f]{32}$")]
    evidence_ref: str | None = None


class ToolCallPendingMeta(_BaseMeta):
    """Metadata for ``tool_call_pending`` events (ADR-030 D1).

    Appended by ``process_tool_calls`` in the COUNTDOWN_CONFIRM/HARD_CONFIRM
    branch — persists the full payload of a gated call so the confirm endpoint
    can later reconstruct it without trusting client-supplied fields.

    Field set is locked by the constitutional test covering the B1 atomic.
    """

    tool_name: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    tier: Literal["countdown_confirm", "hard_confirm"]
    initiating_agent: str = Field(min_length=1)


class ToolCallCancelledMeta(_BaseMeta):
    """Metadata for ``tool_call_cancelled`` events (ADR-030 D3).

    Appended by the confirm endpoint when the user cancels a pending gated
    call. ``call_id`` ties it to the originating ``TOOL_CALL_PENDING`` for
    the position-anchored still-pending predicate in snapshot + endpoint.

    ``approver_user_id`` records the authenticated canceller (ADR-039 D6,
    P4.5-5). Nullable for backward-compat (same discipline as ToolCallMeta).
    """

    call_id: str = Field(min_length=1)
    approver_user_id: str | None = None


TYPED_METADATA: dict[EventType, type[_BaseMeta]] = {
    EventType.HYPOTHESIS: HypothesisMeta,
    EventType.DECISION: DecisionMeta,
    EventType.REJECTION: RejectionMeta,
    EventType.RETRACTION: RetractionMeta,
    EventType.TOOL_CALL: ToolCallMeta,
    EventType.TOOL_RESULT: ToolResultMeta,
    EventType.AUTONOMY_DECISION: AutonomyDecisionMetadata,
    EventType.AUTONOMY_REFUSAL: AutonomyRefusalMetadata,
    EventType.STATE_TRANSITION: StateTransitionMeta,
    EventType.SUMMARY_SNAPSHOT: SummarySnapshotMeta,
    EventType.EXTERNAL_VALIDATION: ExternalValidationMeta,
    EventType.TOOL_CALL_PENDING: ToolCallPendingMeta,
    EventType.TOOL_CALL_CANCELLED: ToolCallCancelledMeta,
}

# ADR-030 D2/D3: event types that resolve a TOOL_CALL_PENDING (position-anchored
# still-pending predicate). Shared by snapshot (D2) and confirm endpoint (D3).
PENDING_RESOLUTION_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.TOOL_CALL,
        EventType.TOOL_RESULT,
        EventType.TOOL_FAILED,
        EventType.TOOL_CALL_CANCELLED,
    }
)


# ---------------------------------------------------------------------------
# Author format
# ---------------------------------------------------------------------------

# ADR-039 D1: generalised to include user:<id> (P4.5-4).
# bare "user" stays valid (backward-compat for stored events + system default).
_AUTHOR_PATTERN = re.compile(
    r"^(user|user:[a-zA-Z0-9_-]+|system|agent:[a-zA-Z0-9_-]+)$"
)


def is_valid_author(author: str) -> bool:
    """True if `author` matches the valid author set.

    Valid forms (ADR-039 D1, P4.5-4):
      ``user``                  — bare legacy / system-default (backward-compat)
      ``user:<id>``             — authenticated user (P4.5+)
      ``agent:<id>``            — agent
      ``system``                — system

    ``<id>`` is one or more of ``[a-zA-Z0-9_-]``.
    """
    return bool(_AUTHOR_PATTERN.fullmatch(author))


def build_author(agent_id: str) -> str:
    """Return the canonical Event.author string for an agent.

    Single point of truth for the ``agent:<id>`` format.  Raises
    ``ValueError`` on empty ``agent_id`` (defense-in-depth — the
    returned string still passes ``is_valid_author`` at Event
    construction; this guard catches the caller's bug earlier).
    """
    if not agent_id:
        raise ValueError("agent_id must be non-empty")
    return f"agent:{agent_id}"


def build_user_author(user_id: str) -> str:
    """Return the canonical Event.author string for an authenticated user.

    Single point of truth for the ``user:<id>`` format (ADR-039 D1/D7).
    Stamped server-side from the verified Principal — never from the request.
    Raises ``ValueError`` on empty ``user_id``.
    """
    if not user_id:
        raise ValueError("user_id must be non-empty")
    return f"user:{user_id}"


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class MetadataValidationError(ValueError):
    """Raised when metadata fails the per-type schema for a TYPED_METADATA
    event type."""


class RoomNotFoundError(LookupError):
    """Raised on append() when `room_id` does not reference an existing
    room. Validation happens at write time."""


class EventNotFoundError(LookupError):
    """Raised when a read API receives an event_id that does not exist
    AND the empty case has a different semantic meaning. Specifically:
    `get_thread(unknown_id)` raises this rather than returning ``[]``,
    because returning ``[]`` would conflate "unknown id" (a bug) with
    "thread is empty" (impossible — every event is at least the root
    of its own thread). Per Principle 4 — using empty data to express
    unknown is prose hedging in disguise.

    Functions whose empty case IS legitimate (e.g. `get_room_events` of
    a freshly created room) return ``[]`` and do NOT raise this.
    """


ParentInvalidReason = Literal["not_found", "cross_room", "self_parent"]


class InvalidParentError(ValueError):
    """Raised on append() when `parent_id` is invalid in any of three ways.

    Callers that want to react differently per failure mode should
    discriminate on `.reason`, not parse `str(e)`:

        try:
            store.append(event)
        except InvalidParentError as e:
            match e.reason:
                case "not_found":   ...
                case "cross_room":  ...
                case "self_parent": ...

    `.reason` is a `Literal[...]`, so type checkers can flag missing
    cases in a `match` over it.
    """

    reason: ParentInvalidReason

    def __init__(self, reason: ParentInvalidReason, message: str = "") -> None:
        self.reason = reason
        super().__init__(message or f"parent_id invalid: {reason}")


# ---------------------------------------------------------------------------
# Metadata validation (parser, not routing logic)
# ---------------------------------------------------------------------------


def validate_metadata(event_type: EventType, metadata: dict[str, Any]) -> dict[str, Any]:
    """Validate metadata against the per-type schema if one exists.

    For TYPED_METADATA event types: parse via Pydantic and return the
    normalized dict (with defaults filled in). For other types: pass the
    dict through unchanged.

    This is a parser, not a routing decision — it's safe to live in
    event.py rather than event_store.py.

    Raises:
        MetadataValidationError: validation failed for a typed event type.
    """
    schema = TYPED_METADATA.get(event_type)
    if schema is None:
        return metadata
    try:
        return schema.model_validate(metadata).model_dump()
    except ValidationError as e:
        raise MetadataValidationError(f"metadata for {event_type.value} failed schema: {e}") from e


# ---------------------------------------------------------------------------
# Event and Relation
# ---------------------------------------------------------------------------


class Event(BaseModel):
    """An immutable event in the append-only event log.

    `metadata` is `dict[str, Any]` for storage flexibility; per-type
    schema validation happens via `validate_metadata()` at append time.
    Application-layer `frozen=True` plus the schema-level UPDATE/DELETE
    triggers give overlapping append-only enforcement (see event-model.md
    §"Append-only enforcement").
    """

    id: EventId
    parent_id: EventId | None = None
    room_id: RoomId
    type: EventType
    author: str
    timestamp: TimestampMs
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("author")
    @classmethod
    def _check_author(cls, v: str) -> str:
        if not is_valid_author(v):
            raise ValueError(f"author must match 'user' | 'agent:<id>' | 'system', got {v!r}")
        return v


class Relation(BaseModel):
    """A structural edge between events. Persisted in the `relations` table,
    which is a CACHE — not append-only. Can be rebuilt from events at any
    time via the same pure `extract_structural_relations` function.
    """

    event_id: EventId
    relation_type: RelationType
    target_event_id: EventId
    extracted_at: TimestampMs

    model_config = ConfigDict(frozen=True, extra="forbid")
