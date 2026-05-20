"""Constitutional tests for the autonomy module.

These lock in the schema-level invariants the autonomy gate depends on.
If a future PR breaks one, do NOT "fix the test" — investigate whether
the invariant is still valid, and if it must change, write an ADR.

See ``tests/core/test_constitution.py`` for the precedent docstring.
"""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from orchestrator.autonomy.emission import emit_gate_decision
from orchestrator.autonomy.scoring import (
    AutonomyTier,
    Operation,
    ThresholdConfig,
    ToolMeta,
    UnknownToolError,
    decide_tier,
)
from orchestrator.core.event import EventType, TimestampMs, generate_room_id, now_ms
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.types import AgentAutonomyThresholds


@pytest.mark.parametrize(
    "cls",
    [ThresholdConfig, AgentAutonomyThresholds],
    ids=["ThresholdConfig", "AgentAutonomyThresholds"],
)
def test_constitution_threshold_auto_strictly_greater_than_confirm(
    cls: type[ThresholdConfig] | type[AgentAutonomyThresholds],
) -> None:
    """Both threshold-carrying classes must enforce
    ``threshold_auto > threshold_confirm`` at Pydantic-validation time.

    Why: ``decide_tier`` (autonomy gate) selects AUTO_EXECUTE vs
    COUNTDOWN_CONFIRM vs HARD_CONFIRM by ordered comparison on these
    two thresholds. ADR-005 Decision 4 specifies COUNTDOWN_CONFIRM as
    the band ``[confirm, auto)``; equal values collapse the band to
    zero-width, and inverted values reverse the rule into undefined
    behavior dependent on if/elif ordering rather than on a clean
    invariant.

    The invariant is parameterized over BOTH classes because the YAML
    load path uses ``AgentAutonomyThresholds`` while ``decide_tier``
    consumes ``ThresholdConfig`` — if either drops the validator, a
    construction site can produce an unsafe instance. This test fails
    on any such drift.

    Boundary cases exercised:

    - equal (auto == confirm): zero-width COUNTDOWN_CONFIRM band.
    - inverted (auto < confirm): rule order undefined.
    - valid (auto > confirm, minimal gap of 1): must accept.
    """
    with pytest.raises(ValidationError, match="strictly greater"):
        cls(threshold_auto=5, threshold_confirm=5, user_intent_modifier=0)

    with pytest.raises(ValidationError, match="strictly greater"):
        cls(threshold_auto=3, threshold_confirm=7, user_intent_modifier=0)

    instance = cls(threshold_auto=6, threshold_confirm=5, user_intent_modifier=0)
    assert instance.threshold_auto == 6
    assert instance.threshold_confirm == 5


def test_constitution_hard_confirm_unreachable_when_effective_confirm_clamped() -> None:
    """When ``effective_threshold_confirm`` is clamped to 0 by ``max(0, …)``,
    HARD_CONFIRM must be structurally unreachable for any score in [0, 10].

    ADR-005 §5(c) establishes the floor: ``effective_threshold_confirm =
    max(0, threshold_confirm - modifier)``. When the modifier equals or
    exceeds ``threshold_confirm``, the floor kicks in and the confirm band
    collapses to 0 — meaning ``score >= 0`` is always true, and the
    COUNTDOWN_CONFIRM branch absorbs all scores that would otherwise have
    fallen to HARD_CONFIRM.

    This invariant is load-bearing: ADR-005 §5 Alternative B (binary router
    — skip scoring when user is explicit) was **rejected** because it would
    have removed Hard Guards' authority to refuse user-cooperative
    destructive calls. The floor is the deliberate middle ground: user
    intent can lower the confirm threshold to 0 (no HARD_CONFIRM prompt),
    but the destructive-action refusal layer (P1.3 Hard Guards) is what
    prevents those calls from executing unchecked, not this scorer's
    HARD_CONFIRM tier.

    If this test fails: do NOT remove the clamp or adjust the formula.
    Investigate whether P1.3 Hard Guards now covers the cases you expected
    to route through HARD_CONFIRM. If it does, write an ADR revising §5(c).

    Tuples exercised: (threshold_confirm=2, modifier=5) and
    (threshold_confirm=3, modifier=3) — both satisfy modifier >= threshold_confirm.
    Each tuple is combined with all 11 score values [0..10] → 22 combinations.
    """
    combinations = [
        # (threshold_auto, threshold_confirm, modifier)
        (8, 2, 5),  # modifier > confirm → eff_confirm = max(0, -3) = 0
        (7, 3, 3),  # modifier == confirm → eff_confirm = max(0, 0) = 0
    ]
    for auto, confirm, modifier in combinations:
        thresholds = ThresholdConfig(
            threshold_auto=auto,
            threshold_confirm=confirm,
            user_intent_modifier=modifier,
        )
        for s in range(0, 11):
            result = decide_tier(s, thresholds, user_explicit_intent=True, tool_id="test_tool")
            assert result.tier != AutonomyTier.HARD_CONFIRM, (
                f"HARD_CONFIRM was produced with score={s}, auto={auto}, "
                f"confirm={confirm}, modifier={modifier} — effective_confirm "
                f"should be 0 (clamped), making HARD_CONFIRM unreachable. "
                f"trace={result.trace}"
            )
            assert result.trace.threshold_confirm_effective == 0, (
                f"expected effective_confirm=0 but got "
                f"{result.trace.threshold_confirm_effective} for score={s}, "
                f"auto={auto}, confirm={confirm}, modifier={modifier}"
            )


def test_constitution_unknown_tool_attempt_always_emits_refusal_event() -> None:
    """Every ``UnknownToolError`` path through ``emit_gate_decision`` must
    produce exactly one ``autonomy_refusal`` event, appended **before**
    the exception propagates.

    Why: absence-as-signal violates Principle 4 — a missing event row
    looks identical to "the gate was never called". ADR-007 §3 requires
    synchronous emission before raise. This test verifies the invariant
    holds for any tools dict that produces a registry-miss.

    Uses a real in-memory EventStore so that both the append mechanics
    (metadata validation, room check) and the event count assertion are
    exercised in the same pass.

    If this test fails: do NOT remove the ``event_store.append()`` call
    from ``emission.py``. Investigate whether the emit-before-raise
    contract was broken; if the design must change, amend ADR-007.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()

    rid = generate_room_id()
    store.append_room(Room(id=rid, type=RoomType.RESEARCH, created_at=TimestampMs(now_ms())))

    thresholds = ThresholdConfig(threshold_auto=8, threshold_confirm=5, user_intent_modifier=2)

    # Three distinct unknown-tool scenarios — all must produce exactly one
    # autonomy_refusal event each.
    unknown_ops = [
        Operation(
            tool_id="ghost_tool", initiating_agent="agent:operator", user_explicit_intent=False
        ),
        Operation(
            tool_id="renamed_tool", initiating_agent="agent:prober", user_explicit_intent=True
        ),
        Operation(
            tool_id="typo_tol", initiating_agent="agent:operator", user_explicit_intent=False
        ),
    ]
    known_tools: dict[str, ToolMeta] = {}  # empty — all tool_ids are unknown

    for op in unknown_ops:
        with pytest.raises(UnknownToolError):
            emit_gate_decision(
                op, known_tools, thresholds, store, room_id=rid, author="agent:operator"
            )

    events = store.get_room_events(rid)
    refusal_events = [e for e in events if e.type == EventType.AUTONOMY_REFUSAL]
    decision_events = [e for e in events if e.type == EventType.AUTONOMY_DECISION]

    assert len(refusal_events) == 3, (
        f"Expected 3 autonomy_refusal events (one per unknown-tool attempt), "
        f"got {len(refusal_events)}. Missing events = audit gap."
    )
    assert len(decision_events) == 0, (
        "No autonomy_decision events expected when all attempts are unknown-tool refusals."
    )
    sorted_events = sorted(refusal_events, key=lambda e: e.metadata["operation_tool_id"])
    sorted_ops = sorted(unknown_ops, key=lambda op: op.tool_id)
    for ev, op in zip(sorted_events, sorted_ops, strict=True):
        assert ev.metadata["operation_tool_id"] == op.tool_id
        assert ev.metadata["refusal_reason"] == "unknown_tool"
