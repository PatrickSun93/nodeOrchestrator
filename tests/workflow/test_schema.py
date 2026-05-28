"""Schema invariant tests for orchestrator.workflow.schema.

Covers test-coverage-standard.md §5 (boundary validators) and §6 (schema
invariants) for TaskState and OverrideEntry. One test per constrained
Field, plus frozen/extra-forbid/Literal assertions.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.workflow.schema import OverrideEntry, TaskState, WorkflowState

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


def _valid_task_state(**overrides: object) -> TaskState:
    defaults: dict[str, object] = {
        "task_id": "W-001-impl",
        "state": WorkflowState.AWAITING_JUNIOR_IMPL,
        "last_transition_at": _NOW,
    }
    defaults.update(overrides)
    return TaskState(**defaults)  # type: ignore[arg-type]


def _valid_override(**overrides: object) -> OverrideEntry:
    defaults: dict[str, object] = {
        "timestamp": _NOW,
        "actor": "architect",
        "from_state": WorkflowState.AWAITING_JUNIOR_IMPL,
        "to_state": WorkflowState.AWAITING_ARCHITECT_DECISION,
        "reason": "blocking finding in R0-A",
    }
    defaults.update(overrides)
    return OverrideEntry(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# WorkflowState enum
# ---------------------------------------------------------------------------


def test_workflow_state_exact_10_values() -> None:
    """10 canonical states per ADR-008 Decision 6 + Amendment 2 (W-005).

    Amendment 2 added awaiting_senior_revision (routing absorption phase
    previously implicit between architect_decision and PR_merge).
    """
    expected = {
        "awaiting_brief",
        "awaiting_senior_plan",
        "awaiting_architect_accept",
        "awaiting_junior_impl",
        "awaiting_senior_plan_vs_impl",
        "awaiting_R0_A",
        "awaiting_architect_decision",
        "awaiting_senior_revision",  # W-005 Amendment 2
        "awaiting_PR_merge",
        "closed",
    }
    actual = {s.value for s in WorkflowState}
    assert actual == expected, (
        f"WorkflowState has wrong values.\nExpected: {sorted(expected)}\nActual: {sorted(actual)}"
    )


# ---------------------------------------------------------------------------
# TaskState — §6 frozen, extra-forbid, field constraints
# ---------------------------------------------------------------------------


def test_task_state_frozen() -> None:
    ts = _valid_task_state()
    with pytest.raises(ValidationError):
        ts.state = WorkflowState.CLOSED


def test_task_state_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        TaskState(  # type: ignore[call-arg]
            task_id="W-001",
            state=WorkflowState.AWAITING_JUNIOR_IMPL,
            last_transition_at=_NOW,
            unknown_field="bad",
        )


def test_task_state_task_id_empty_raises() -> None:
    with pytest.raises(ValidationError):
        _valid_task_state(task_id="")


def test_task_state_cycle_zero_raises() -> None:
    with pytest.raises(ValidationError):
        _valid_task_state(cycle=0)


def test_task_state_cycle_negative_raises() -> None:
    with pytest.raises(ValidationError):
        _valid_task_state(cycle=-1)


def test_task_state_cycle_one_valid() -> None:
    ts = _valid_task_state(cycle=1)
    assert ts.cycle == 1


# ---------------------------------------------------------------------------
# OverrideEntry — §5 actor Literal, §6 frozen, extra-forbid
# ---------------------------------------------------------------------------


def test_override_entry_frozen() -> None:
    oe = _valid_override()
    with pytest.raises(ValidationError):
        oe.reason = "changed"


def test_override_entry_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        OverrideEntry(  # type: ignore[call-arg]
            timestamp=_NOW,
            actor="architect",
            from_state=WorkflowState.AWAITING_JUNIOR_IMPL,
            to_state=WorkflowState.AWAITING_ARCHITECT_DECISION,
            reason="test",
            unexpected="bad",
        )


def test_override_entry_invalid_actor_raises() -> None:
    with pytest.raises(ValidationError):
        _valid_override(actor="junior")


def test_override_entry_reason_empty_raises() -> None:
    with pytest.raises(ValidationError):
        _valid_override(reason="")
