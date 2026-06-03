"""Tests for src/orchestrator/derived/snapshot.py.

Coverage:
  §6 schema invariants: HypothesisRef, DecisionRef, ToolCallRef,
     StateTransitionRef, Snapshot (5 classes x >=4 tests = >=20 tests).
  §1 cross-module: event stream → produce_snapshot → assert fields.
  §5 boundary validators: event_count / decision_count ge=0.
  §2 concurrency invariant: same (events, room, snapshot_at) → same Snapshot.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from orchestrator.core.event import (
    Event,
    EventType,
    TimestampMs,
    ToolCallCancelledMeta,
    ToolCallPendingMeta,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.room import Room, RoomType
from orchestrator.derived.snapshot import (
    DecisionRef,
    HypothesisRef,
    Snapshot,
    StateTransitionRef,
    ToolCallRef,
    produce_snapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROOM_ID = generate_room_id()
_ROOM = Room(id=_ROOM_ID, type=RoomType.RESEARCH, state="convergence")
_TS = TimestampMs(now_ms())


def _evt(
    *,
    event_type: EventType,
    author: str = "user",
    content: str = "content",
    metadata: dict[str, Any] | None = None,
    timestamp: int | None = None,
) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=_ROOM_ID,
        type=event_type,
        author=author,
        timestamp=TimestampMs(timestamp if timestamp is not None else now_ms()),
        content=content,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# §6 schema invariants — HypothesisRef (4 tests)
# ---------------------------------------------------------------------------


def test_hypothesis_ref_frozen() -> None:
    """HypothesisRef is frozen — mutating a field raises."""
    hr = HypothesisRef(event_id="evt_abc")
    with pytest.raises((ValidationError, TypeError)):
        hr.event_id = "evt_other"


def test_hypothesis_ref_extra_forbid() -> None:
    """HypothesisRef rejects unknown fields."""
    with pytest.raises(ValidationError):
        HypothesisRef(event_id="evt_abc", extra_field="x")  # type: ignore[call-arg]


def test_hypothesis_ref_required_field_absent() -> None:
    """HypothesisRef requires event_id."""
    with pytest.raises(ValidationError):
        HypothesisRef()  # type: ignore[call-arg]


def test_hypothesis_ref_wrong_type() -> None:
    """HypothesisRef rejects list for event_id."""
    with pytest.raises(ValidationError):
        HypothesisRef(event_id=["not", "a", "string"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# §6 schema invariants — DecisionRef (4 tests)
# ---------------------------------------------------------------------------


def test_decision_ref_frozen() -> None:
    dr = DecisionRef(event_id="evt_d1")
    with pytest.raises((ValidationError, TypeError)):
        dr.event_id = "evt_d2"


def test_decision_ref_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        DecisionRef(event_id="evt_d1", unknown=True)  # type: ignore[call-arg]


def test_decision_ref_required_field_absent() -> None:
    with pytest.raises(ValidationError):
        DecisionRef()  # type: ignore[call-arg]


def test_decision_ref_wrong_type() -> None:
    with pytest.raises(ValidationError):
        DecisionRef(event_id={"nested": "dict"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# §6 schema invariants — ToolCallRef (4 tests)
# ---------------------------------------------------------------------------


def test_tool_call_ref_frozen() -> None:
    tcr = ToolCallRef(event_id="evt_tc", tool_name="read_file", autonomy_tier="countdown_confirm")
    with pytest.raises((ValidationError, TypeError)):
        tcr.tool_name = "write_file"


def test_tool_call_ref_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        ToolCallRef(
            event_id="evt_tc",
            tool_name="read_file",
            autonomy_tier="countdown_confirm",
            extra=1,  # type: ignore[call-arg]
        )


def test_tool_call_ref_required_field_absent() -> None:
    """ToolCallRef requires all three fields."""
    with pytest.raises(ValidationError):
        ToolCallRef(event_id="evt_tc", tool_name="read_file")  # type: ignore[call-arg]


def test_tool_call_ref_invalid_autonomy_tier() -> None:
    """auto_execute is NOT a valid autonomy_tier for pending tool calls."""
    with pytest.raises(ValidationError):
        ToolCallRef(event_id="evt_tc", tool_name="read_file", autonomy_tier="auto_execute")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# §6 schema invariants — StateTransitionRef (4 tests)
# ---------------------------------------------------------------------------


def test_state_transition_ref_frozen() -> None:
    str_ref = StateTransitionRef(event_id="evt_st", new_state="closed", prior_state="setup")
    with pytest.raises((ValidationError, TypeError)):
        str_ref.new_state = "open"


def test_state_transition_ref_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        StateTransitionRef(
            event_id="evt_st",
            new_state="closed",
            prior_state="setup",
            extra="boom",  # type: ignore[call-arg]
        )


def test_state_transition_ref_required_field_absent() -> None:
    with pytest.raises(ValidationError):
        StateTransitionRef(event_id="evt_st", new_state="closed")  # type: ignore[call-arg]


def test_state_transition_ref_wrong_type() -> None:
    with pytest.raises(ValidationError):
        StateTransitionRef(event_id="evt_st", new_state=["bad"], prior_state="setup")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# §6 schema invariants — Snapshot (5 tests including §5 boundary validators)
# ---------------------------------------------------------------------------


def _minimal_snapshot(**overrides: Any) -> Snapshot:
    defaults: dict[str, Any] = dict(
        room_id=_ROOM_ID,
        room_type=RoomType.RESEARCH,
        room_state="convergence",
        snapshot_at=_TS,
        event_count=0,
        decision_count=0,
        open_hypotheses=[],
        closed_decisions=[],
        tool_calls_pending_confirm=[],
        last_state_transition=None,
        participants=[],
    )
    defaults.update(overrides)
    return Snapshot(**defaults)


def test_snapshot_frozen() -> None:
    snap = _minimal_snapshot()
    with pytest.raises((ValidationError, TypeError)):
        snap.event_count = 99


def test_snapshot_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        _minimal_snapshot(unknown_field="surprise")


def test_snapshot_required_field_absent() -> None:
    with pytest.raises(ValidationError):
        Snapshot(  # type: ignore[call-arg]
            room_id=_ROOM_ID,
            room_type=RoomType.RESEARCH,
            room_state="convergence",
            snapshot_at=_TS,
            # missing event_count, decision_count, etc.
        )


def test_snapshot_event_count_ge_zero() -> None:
    """§5 boundary: event_count must be ≥ 0."""
    with pytest.raises(ValidationError):
        _minimal_snapshot(event_count=-1)


def test_snapshot_decision_count_ge_zero() -> None:
    """§5 boundary: decision_count must be ≥ 0."""
    with pytest.raises(ValidationError):
        _minimal_snapshot(decision_count=-1)


# ---------------------------------------------------------------------------
# §1 cross-module: produce_snapshot derivation
# ---------------------------------------------------------------------------


def test_produce_snapshot_empty_events() -> None:
    """Empty event stream → all collections empty, counts zero."""
    snap = produce_snapshot([], _ROOM, snapshot_at=_TS)
    assert snap.room_id == _ROOM_ID
    assert snap.room_type == RoomType.RESEARCH
    assert snap.room_state == "convergence"
    assert snap.snapshot_at == int(_TS)
    assert snap.event_count == 0
    assert snap.decision_count == 0
    assert snap.open_hypotheses == []
    assert snap.closed_decisions == []
    assert snap.tool_calls_pending_confirm == []
    assert snap.last_state_transition is None
    assert snap.participants == []


def test_produce_snapshot_open_hypothesis() -> None:
    """HYPOTHESIS with no closing event → appears in open_hypotheses."""
    hyp = _evt(event_type=EventType.HYPOTHESIS, author="user", metadata={"confidence": 0.7})
    snap = produce_snapshot([hyp], _ROOM, snapshot_at=_TS)
    assert len(snap.open_hypotheses) == 1
    assert snap.open_hypotheses[0].event_id == hyp.id


def test_produce_snapshot_hypothesis_closed_by_decision() -> None:
    """HYPOTHESIS cited in DecisionMeta.based_on → not in open_hypotheses."""
    hyp = _evt(event_type=EventType.HYPOTHESIS, author="user", metadata={"confidence": 0.7})
    decision = _evt(
        event_type=EventType.DECISION,
        author="user",
        metadata={"based_on": [hyp.id], "trade_offs": {}},
    )
    snap = produce_snapshot([hyp, decision], _ROOM, snapshot_at=_TS)
    assert snap.open_hypotheses == []
    assert len(snap.closed_decisions) == 1
    assert snap.closed_decisions[0].event_id == decision.id


def test_produce_snapshot_hypothesis_closed_by_rejection() -> None:
    """HYPOTHESIS cited in RejectionMeta.rejects → not in open_hypotheses."""
    hyp = _evt(event_type=EventType.HYPOTHESIS, author="user", metadata={"confidence": 0.8})
    rejection = _evt(
        event_type=EventType.REJECTION,
        author="user",
        metadata={"rejects": hyp.id, "reason": "invalid"},
    )
    snap = produce_snapshot([hyp, rejection], _ROOM, snapshot_at=_TS)
    assert snap.open_hypotheses == []


def test_produce_snapshot_closed_decision_retracted() -> None:
    """DECISION subsequently retracted → not in closed_decisions."""
    decision = _evt(
        event_type=EventType.DECISION,
        author="user",
        metadata={"based_on": [generate_event_id()], "trade_offs": {}},
    )
    retraction = _evt(
        event_type=EventType.RETRACTION,
        author="user",
        metadata={"retracts": decision.id, "reason": "changed mind"},
    )
    snap = produce_snapshot([decision, retraction], _ROOM, snapshot_at=_TS)
    assert snap.closed_decisions == []


def test_produce_snapshot_participants_sorted() -> None:
    """Agent IDs from UTTERANCE events → sorted alphabetically."""
    utterance_z = _evt(event_type=EventType.UTTERANCE, author="agent:zebra", content="hi")
    utterance_a = _evt(event_type=EventType.UTTERANCE, author="agent:alpha", content="hi")
    snap = produce_snapshot([utterance_z, utterance_a], _ROOM, snapshot_at=_TS)
    assert snap.participants == ["alpha", "zebra"]


def test_produce_snapshot_last_state_transition() -> None:
    """Most-recent STATE_TRANSITION → last_state_transition."""
    st1 = _evt(
        event_type=EventType.STATE_TRANSITION,
        author="system",
        metadata={"prior_state": "setup", "new_state": "exploration"},
        timestamp=1000,
    )
    st2 = _evt(
        event_type=EventType.STATE_TRANSITION,
        author="system",
        metadata={"prior_state": "exploration", "new_state": "convergence"},
        timestamp=2000,
    )
    snap = produce_snapshot([st1, st2], _ROOM, snapshot_at=_TS)
    assert snap.last_state_transition is not None
    assert snap.last_state_transition.event_id == st2.id
    assert snap.last_state_transition.new_state == "convergence"
    assert snap.last_state_transition.prior_state == "exploration"


def test_produce_snapshot_no_state_transition() -> None:
    """No STATE_TRANSITION events → last_state_transition is None."""
    snap = produce_snapshot([_evt(event_type=EventType.USER_INPUT)], _ROOM, snapshot_at=_TS)
    assert snap.last_state_transition is None


def test_produce_snapshot_decision_count() -> None:
    """decision_count counts DECISION + DECISION_PIVOT + REJECTION + RETRACTION."""
    events = [
        _evt(
            event_type=EventType.DECISION,
            author="user",
            metadata={"based_on": [generate_event_id()], "trade_offs": {}},
        ),
        _evt(event_type=EventType.DECISION_PIVOT, author="user"),
        _evt(
            event_type=EventType.REJECTION,
            author="user",
            metadata={"rejects": generate_event_id(), "reason": "bad"},
        ),
        _evt(
            event_type=EventType.RETRACTION,
            author="user",
            metadata={"retracts": generate_event_id(), "reason": "wrong"},
        ),
        _evt(event_type=EventType.UTTERANCE, author="agent:alpha"),  # not decision-class
    ]
    snap = produce_snapshot(events, _ROOM, snapshot_at=_TS)
    assert snap.decision_count == 4


def _pending_evt(
    *,
    call_id: str,
    tool_name: str = "apply_edit",
    tier: str = "countdown_confirm",
    timestamp: int = 1000,
) -> Event:
    """Helper: make a TOOL_CALL_PENDING event for snapshot B2 tests."""
    return _evt(
        event_type=EventType.TOOL_CALL_PENDING,
        author="agent:operator",
        metadata=ToolCallPendingMeta(
            tool_name=tool_name,
            call_id=call_id,
            params={},
            tier=tier,  # type: ignore[arg-type]
            initiating_agent="operator",
        ).model_dump(),
        timestamp=timestamp,
    )


def test_produce_snapshot_tool_call_pending_confirm() -> None:
    """B2: unconfirmed TOOL_CALL_PENDING → in pending list with correct fields (ADR-030 D2)."""
    p = _pending_evt(call_id="call_001", tool_name="write_file", tier="countdown_confirm")
    snap = produce_snapshot([p], _ROOM, snapshot_at=_TS)
    assert len(snap.tool_calls_pending_confirm) == 1
    ref = snap.tool_calls_pending_confirm[0]
    assert ref.event_id == p.id
    assert ref.tool_name == "write_file"
    assert ref.autonomy_tier == "countdown_confirm"


def test_produce_snapshot_auto_execute_not_pending() -> None:
    """AUTO_EXECUTE TOOL_CALL (no TOOL_CALL_PENDING) → NOT in pending list."""
    tc_event = _evt(
        event_type=EventType.TOOL_CALL,
        author="agent:operator",
        metadata={"tool_name": "read_file", "call_id": "call_002", "params": {}},
        timestamp=1001,
    )
    snap = produce_snapshot([tc_event], _ROOM, snapshot_at=_TS)
    assert snap.tool_calls_pending_confirm == []


def test_produce_snapshot_pending_resolved_by_tool_call() -> None:
    """B2: TOOL_CALL after pending event for same call_id → drops from pending list."""
    p = _pending_evt(call_id="call_003", timestamp=1000)
    approval = _evt(
        event_type=EventType.TOOL_CALL,
        author="agent:operator",
        metadata={"tool_name": "apply_edit", "call_id": "call_003", "params": {}},
        timestamp=1001,
    )
    snap = produce_snapshot([p, approval], _ROOM, snapshot_at=_TS)
    assert snap.tool_calls_pending_confirm == []


def test_produce_snapshot_pending_resolved_by_tool_result() -> None:
    """B2: TOOL_RESULT after pending event for same call_id → drops from pending list."""
    p = _pending_evt(call_id="call_res", timestamp=1000)
    result = _evt(
        event_type=EventType.TOOL_RESULT,
        author="agent:operator",
        metadata={"call_id": "call_res", "success": True},
        timestamp=1001,
    )
    snap = produce_snapshot([p, result], _ROOM, snapshot_at=_TS)
    assert snap.tool_calls_pending_confirm == []


def test_produce_snapshot_pending_resolved_by_cancelled() -> None:
    """B2: TOOL_CALL_CANCELLED after pending event for same call_id → drops from pending list."""
    p = _pending_evt(call_id="call_cancel", timestamp=1000)
    cancelled = _evt(
        event_type=EventType.TOOL_CALL_CANCELLED,
        author="agent:operator",
        metadata=ToolCallCancelledMeta(call_id="call_cancel").model_dump(),
        timestamp=1001,
    )
    snap = produce_snapshot([p, cancelled], _ROOM, snapshot_at=_TS)
    assert snap.tool_calls_pending_confirm == []


def test_produce_snapshot_pending_cross_turn_collision_y2() -> None:
    """B2 Y2: prior-turn TOOL_RESULT with same call_id does NOT resolve a later TOOL_CALL_PENDING.

    A turn-1 TOOL_RESULT(abc) followed by a turn-5 TOOL_CALL_PENDING(abc): the result
    is BEFORE the pending event, so position-anchored scan ignores it — turn-5 still listed.
    """
    prior_result = _evt(
        event_type=EventType.TOOL_RESULT,
        author="agent:operator",
        metadata={"call_id": "abc", "success": True},
        timestamp=1000,
    )
    later_pending = _pending_evt(call_id="abc", timestamp=5000)
    snap = produce_snapshot([prior_result, later_pending], _ROOM, snapshot_at=_TS)
    # The prior result is BEFORE the pending event; position-anchored scan ignores it.
    assert len(snap.tool_calls_pending_confirm) == 1
    assert snap.tool_calls_pending_confirm[0].event_id == later_pending.id


def test_produce_snapshot_hard_confirm_pending() -> None:
    """B2: TOOL_CALL_PENDING with hard_confirm tier → autonomy_tier preserved."""
    p = _pending_evt(call_id="call_hc", tier="hard_confirm")
    snap = produce_snapshot([p], _ROOM, snapshot_at=_TS)
    assert len(snap.tool_calls_pending_confirm) == 1
    assert snap.tool_calls_pending_confirm[0].autonomy_tier == "hard_confirm"


def test_produce_snapshot_purity_same_inputs_same_output() -> None:
    """§2 concurrency: same (events, room, snapshot_at) → identical Snapshot."""
    events = [
        _evt(event_type=EventType.UTTERANCE, author="agent:alpha"),
        _evt(
            event_type=EventType.HYPOTHESIS,
            author="user",
            metadata={"confidence": 0.6},
        ),
    ]
    ts = TimestampMs(12345678)
    snap1 = produce_snapshot(events, _ROOM, snapshot_at=ts)
    snap2 = produce_snapshot(events, _ROOM, snapshot_at=ts)
    assert snap1 == snap2


def test_produce_snapshot_event_count() -> None:
    """event_count reflects total input event list length."""
    events = [_evt(event_type=EventType.USER_INPUT) for _ in range(5)]
    snap = produce_snapshot(events, _ROOM, snapshot_at=_TS)
    assert snap.event_count == 5


# ---------------------------------------------------------------------------
# ADR-030 D2 supersedes old M-R1 "unknown" tier behavior:
# The pending list is now derived from TOOL_CALL_PENDING events only.
# A plain TOOL_CALL (AUTO_EXECUTE path) never appears in tool_calls_pending_confirm.
# ---------------------------------------------------------------------------


def test_produce_snapshot_plain_tool_call_not_in_pending_list() -> None:
    """ADR-030 D2: plain TOOL_CALL (AUTO_EXECUTE) → NOT in tool_calls_pending_confirm.

    The new predicate derives pending from TOOL_CALL_PENDING only; the old
    'unknown' anomaly path (ADR-014 M-R1) is superseded by ADR-030 D2.
    """
    tc_event = _evt(
        event_type=EventType.TOOL_CALL,
        author="agent:operator",
        metadata={"tool_name": "read_file", "call_id": "call_auto", "params": {}},
    )
    snap = produce_snapshot([tc_event], _ROOM, snapshot_at=_TS)
    assert snap.tool_calls_pending_confirm == []


# ---------------------------------------------------------------------------
# M-Y4: §3-cleanup — malformed metadata raises ValidationError (strict propagation)
# ---------------------------------------------------------------------------


def test_produce_snapshot_malformed_decision_metadata_raises() -> None:
    """DECISION event with malformed based_on → produce_snapshot raises ValidationError.

    Per ADR-014 D7 strict-propagation: no silent swallow.
    """
    bad_decision = _evt(
        event_type=EventType.DECISION,
        author="user",
        metadata={"based_on": "not_a_list", "trade_offs": {}},  # based_on must be list
    )
    with pytest.raises(ValidationError):
        produce_snapshot([bad_decision], _ROOM, snapshot_at=_TS)


def test_produce_snapshot_malformed_retraction_metadata_raises() -> None:
    """RETRACTION event with malformed retracts field → produce_snapshot raises."""
    bad_retraction = _evt(
        event_type=EventType.RETRACTION,
        author="user",
        metadata={"retracts": ["should_be_str_not_list"], "reason": "oops"},
    )
    with pytest.raises(ValidationError):
        produce_snapshot([bad_retraction], _ROOM, snapshot_at=_TS)


def test_produce_snapshot_malformed_state_transition_metadata_raises() -> None:
    """STATE_TRANSITION event with malformed metadata → produce_snapshot raises."""
    bad_st = _evt(
        event_type=EventType.STATE_TRANSITION,
        author="system",
        metadata={"new_state": "", "prior_state": "setup"},  # new_state min_length=1 fails
    )
    with pytest.raises(ValidationError):
        produce_snapshot([bad_st], _ROOM, snapshot_at=_TS)
