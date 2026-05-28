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


def test_produce_snapshot_tool_call_pending_confirm() -> None:
    """TOOL_CALL with preceding countdown_confirm AUTONOMY_DECISION → in pending list."""
    autonomy_event = _evt(
        event_type=EventType.AUTONOMY_DECISION,
        author="agent:operator",
        metadata={
            "operation_tool_id": "write_file",
            "operation_initiating_agent": "operator",
            "user_explicit_intent": False,
            "score": 3,
            "tier": "countdown_confirm",
            "reversibility_score": 3,
            "threshold_auto_raw": 8,
            "threshold_confirm_raw": 5,
            "user_intent_modifier": 2,
            "threshold_auto_effective": 6,
            "threshold_confirm_effective": 3,
            "rule": "score_between_confirm_and_auto",
        },
        timestamp=1000,
    )
    tc_event = _evt(
        event_type=EventType.TOOL_CALL,
        author="agent:operator",
        metadata={"tool_name": "write_file", "call_id": "call_001", "params": {}},
        timestamp=1001,
    )
    snap = produce_snapshot([autonomy_event, tc_event], _ROOM, snapshot_at=_TS)
    assert len(snap.tool_calls_pending_confirm) == 1
    assert snap.tool_calls_pending_confirm[0].tool_name == "write_file"
    assert snap.tool_calls_pending_confirm[0].autonomy_tier == "countdown_confirm"


def test_produce_snapshot_auto_execute_not_pending() -> None:
    """TOOL_CALL with AUTO_EXECUTE AUTONOMY_DECISION → NOT in pending list."""
    autonomy_event = _evt(
        event_type=EventType.AUTONOMY_DECISION,
        author="agent:operator",
        metadata={
            "operation_tool_id": "read_file",
            "operation_initiating_agent": "operator",
            "user_explicit_intent": True,
            "score": 10,
            "tier": "auto_execute",
            "reversibility_score": 10,
            "threshold_auto_raw": 8,
            "threshold_confirm_raw": 5,
            "user_intent_modifier": 2,
            "threshold_auto_effective": 6,
            "threshold_confirm_effective": 3,
            "rule": "score_ge_auto",
        },
        timestamp=1000,
    )
    tc_event = _evt(
        event_type=EventType.TOOL_CALL,
        author="agent:operator",
        metadata={"tool_name": "read_file", "call_id": "call_002", "params": {}},
        timestamp=1001,
    )
    snap = produce_snapshot([autonomy_event, tc_event], _ROOM, snapshot_at=_TS)
    assert snap.tool_calls_pending_confirm == []


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
