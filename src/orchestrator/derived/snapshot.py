"""Derived snapshot: state-at-time-X structured view over the event stream.

Pure function; no LLM, no I/O, no event_store calls.
Constitutional invariant: test_constitution_no_llm_calls_in_derived_module.
See ADR-014 for vocabulary locks + derivation predicate specifications.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.core.event import (
    AutonomyDecisionMetadata,
    DecisionMeta,
    Event,
    EventType,
    RejectionMeta,
    RetractionMeta,
    RoomId,
    StateTransitionMeta,
    TimestampMs,
    ToolCallMeta,
)
from orchestrator.core.room import Room, RoomType


class HypothesisRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str


class DecisionRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str


class ToolCallRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    tool_name: str
    # "unknown" per ADR-014 D2.3 anomaly path (TC without preceding correlated AD).
    autonomy_tier: Literal["countdown_confirm", "hard_confirm", "unknown"]


class StateTransitionRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    new_state: str
    prior_state: str


class Snapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    room_id: RoomId
    room_type: RoomType
    room_state: str
    snapshot_at: int  # ms timestamp; caller-provided per ADR-014 D1 clock-injection
    event_count: int = Field(ge=0)
    decision_count: int = Field(ge=0)
    open_hypotheses: list[HypothesisRef]
    closed_decisions: list[DecisionRef]
    tool_calls_pending_confirm: list[ToolCallRef]
    last_state_transition: StateTransitionRef | None
    participants: list[str]  # sorted alphabetically by agent_id; deterministic ordering


# Per ADR-014 D2.4: agent participation tracked via event types that carry per-event
# author identity unambiguously (UTTERANCE + ops gate + Logger snapshot).
# Decision-class events (DECISION/HYPOTHESIS/REJECTION/RETRACTION) excluded to avoid
# double-count — agents that decide also typically utter; counting via UTTERANCE alone
# preserves single-event-per-agent participation semantic. Future "silent voter" agents
# may motivate revisit (P1.7+ scope).
_AGENT_PARTICIPATION_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.UTTERANCE,
        EventType.SUMMARY_SNAPSHOT,
        EventType.TOOL_CALL,
        EventType.AUTONOMY_DECISION,
        EventType.AUTONOMY_REFUSAL,
    }
)

# Event types that count as decision-class for decision_count field per ADR-014 D2.6.
_DECISION_CLASS_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.DECISION,
        EventType.DECISION_PIVOT,
        EventType.REJECTION,
        EventType.RETRACTION,
    }
)

_AGENT_PREFIX = "agent:"


def produce_snapshot(
    events: list[Event],
    room: Room,
    *,
    snapshot_at: TimestampMs,
) -> Snapshot:
    """Pure derivation of state-at-time-X structured view.

    Caller provides snapshot_at (typically core.event.now_ms()) per ADR-014 D1
    clock-injection (purity preserved; wall-clock impurity isolated at caller).
    See ADR-014 D1 (purity contract) + D6 (caller-frozen-time semantic) +
    D2.1-D2.6 (per-field derivation predicates).

    Raises pydantic.ValidationError on malformed typed event metadata per ADR-014 D7.
    Consumers requiring degraded-snapshot mode should catch ValidationError at boundary.
    """
    # Sort events chronologically once; used by all derivation predicates.
    sorted_events = sorted(events, key=lambda e: (e.timestamp, e.id))

    # --- D2.1 open_hypotheses ---
    # H is "open" iff no event cites H via:
    #   DECISION with H.id in DecisionMeta.based_on, OR
    #   REJECTION with RejectionMeta.rejects == H.id, OR
    #   RETRACTION with RetractionMeta.retracts == H.id.
    # Impl scans all events (not strictly "subsequent"); equivalent for valid streams.
    # Per ADR-014 D2.1 any-vs-subsequent clarification.
    hypothesis_event_ids: list[str] = [
        e.id for e in sorted_events if e.type == EventType.HYPOTHESIS
    ]
    closed_hypothesis_ids: set[str] = set()
    for e in sorted_events:
        if e.type == EventType.DECISION:
            d_meta = DecisionMeta.model_validate(e.metadata)
            closed_hypothesis_ids.update(d_meta.based_on)
        elif e.type == EventType.REJECTION:
            rej_meta = RejectionMeta.model_validate(e.metadata)
            closed_hypothesis_ids.add(rej_meta.rejects)
        elif e.type == EventType.RETRACTION:
            ret_meta = RetractionMeta.model_validate(e.metadata)
            closed_hypothesis_ids.add(ret_meta.retracts)
    open_hypotheses = [
        HypothesisRef(event_id=hid)
        for hid in hypothesis_event_ids
        if hid not in closed_hypothesis_ids
    ]

    # --- D2.2 closed_decisions ---
    # DECISION events D where no event retracts D. DECISION_PIVOT excluded.
    # Impl scans all events per ADR-014 D2.2 any-vs-subsequent clarification.
    decision_event_ids: list[str] = [e.id for e in sorted_events if e.type == EventType.DECISION]
    retracted_event_ids: set[str] = set()
    for e in sorted_events:
        if e.type == EventType.RETRACTION:
            ret_meta2 = RetractionMeta.model_validate(e.metadata)
            retracted_event_ids.add(ret_meta2.retracts)
    closed_decisions = [
        DecisionRef(event_id=did) for did in decision_event_ids if did not in retracted_event_ids
    ]

    # --- D2.3 tool_calls_pending_confirm ---
    # For each TOOL_CALL TC, correlate with the most-recent preceding AUTONOMY_DECISION AD
    # where AD.author == TC.author AND AD.metadata.operation_tool_id == TC.metadata.tool_name.
    # TC is pending iff AD.tier in {countdown_confirm, hard_confirm}.
    # Anomaly (no preceding AD): include with tier="unknown" per ADR-014 D2.3 conservative-include.
    latest_ad_tier: dict[tuple[str, str], str] = {}  # (author, tool_name) -> tier
    tool_calls_pending: list[ToolCallRef] = []
    for e in sorted_events:
        if e.type == EventType.AUTONOMY_DECISION:
            ad_meta = AutonomyDecisionMetadata.model_validate(e.metadata)
            latest_ad_tier[(e.author, ad_meta.operation_tool_id)] = ad_meta.tier
        elif e.type == EventType.TOOL_CALL:
            tc_meta = ToolCallMeta.model_validate(e.metadata)
            key = (e.author, tc_meta.tool_name)
            tier = latest_ad_tier.get(key)
            if tier in ("countdown_confirm", "hard_confirm"):
                tool_calls_pending.append(
                    ToolCallRef(
                        event_id=e.id,
                        tool_name=tc_meta.tool_name,
                        autonomy_tier=tier,  # type: ignore[arg-type]
                    )
                )
            elif tier is None:
                # Anomaly path: TC without preceding correlated AD.
                # Conservative-include per ADR-014 D2.3: "unknown" signals the anomaly.
                tool_calls_pending.append(
                    ToolCallRef(
                        event_id=e.id,
                        tool_name=tc_meta.tool_name,
                        autonomy_tier="unknown",
                    )
                )
            # tier == "auto_execute": tool already executed; not pending.

    # --- D2.5 last_state_transition ---
    # STATE_TRANSITION event maximizing (timestamp, id) lex. None if absent.
    st_events = [e for e in sorted_events if e.type == EventType.STATE_TRANSITION]
    last_state_transition: StateTransitionRef | None = None
    if st_events:
        last_st = max(st_events, key=lambda e: (e.timestamp, e.id))
        st_meta = StateTransitionMeta.model_validate(last_st.metadata)
        last_state_transition = StateTransitionRef(
            event_id=last_st.id,
            new_state=st_meta.new_state,
            prior_state=st_meta.prior_state,
        )

    # --- D2.4 participants ---
    # Agent IDs from agent-authored events of participation types; ascending lex.
    participant_ids: set[str] = set()
    for e in sorted_events:
        if e.type in _AGENT_PARTICIPATION_TYPES and e.author.startswith(_AGENT_PREFIX):
            participant_ids.add(e.author[len(_AGENT_PREFIX) :])
    participants = sorted(participant_ids)

    # --- D2.6 decision_count ---
    # Count of all decision-class events per ADR-014 D2.6.
    decision_count = sum(1 for e in sorted_events if e.type in _DECISION_CLASS_TYPES)

    return Snapshot(
        room_id=room.id,
        room_type=room.type,
        room_state=room.state,
        snapshot_at=int(snapshot_at),
        # len(events) reflects fetch-time count per ADR-011 D1 sequential dispatch;
        # revisit at async-reshape per ADR-014 D6 amendment hook.
        event_count=len(events),
        decision_count=decision_count,
        open_hypotheses=open_hypotheses,
        closed_decisions=closed_decisions,
        tool_calls_pending_confirm=tool_calls_pending,
        last_state_transition=last_state_transition,
        participants=participants,
    )
