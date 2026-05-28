"""Behavior tests for orchestrator.workflow.transitions.

Covers: next_state (one test per ADR-008 Decision 1 row), record_override
(rework cycle, frozen copy), evaluate_merge_clean (subprocess behavior),
parse_verdict (frontmatter parsing, boundary validators per §5).

§3 cleanup: subprocess timeout + CalledProcessError covered below.
§4 exception payload: WorkflowError.task_id / .path fields verified.
§5 boundary: parse_verdict rejects invalid verdict values.
§6 schema: ArtifactSnapshot + GateSnapshot frozen/extra-forbid covered.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.workflow.exceptions import WorkflowError
from orchestrator.workflow.schema import OverrideEntry, TaskState, WorkflowState
from orchestrator.workflow.transitions import (
    ArtifactSnapshot,
    GateSnapshot,
    evaluate_merge_clean,
    next_state,
    parse_verdict,
    record_override,
)

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snap(
    *,
    brief_exists: bool = False,
    senior_plan_exists: bool = False,
    adr_status: Literal["proposed", "accepted", "none"] = "none",
    junior_impl_commit_present: bool = False,
    plan_vs_impl_verdict: Literal["clean", "blocking", "needs_architect", "absent"] = "absent",
    r0_a_verdict: Literal["clean", "blocking", "needs_architect", "absent"] = "absent",
    pr_merged: bool = False,
    plan_has_adr: bool | None = None,
) -> ArtifactSnapshot:
    return ArtifactSnapshot(
        brief_exists=brief_exists,
        senior_plan_exists=senior_plan_exists,
        adr_status=adr_status,
        junior_impl_commit_present=junior_impl_commit_present,
        plan_vs_impl_verdict=plan_vs_impl_verdict,
        r0_a_verdict=r0_a_verdict,
        pr_merged=pr_merged,
        plan_has_adr=plan_has_adr,
    )


def _gates(*, merge_clean: bool = True) -> GateSnapshot:
    return GateSnapshot(merge_clean=merge_clean)


def _state(state: WorkflowState = WorkflowState.AWAITING_BRIEF, cycle: int = 1) -> TaskState:
    return TaskState(
        task_id="TEST-001",
        state=state,
        cycle=cycle,
        last_transition_at=_NOW,
    )


# ---------------------------------------------------------------------------
# §6 schema: ArtifactSnapshot + GateSnapshot frozen / extra-forbid
# ---------------------------------------------------------------------------


def test_artifact_snapshot_frozen() -> None:
    from pydantic import ValidationError

    s = _snap()
    with pytest.raises(ValidationError):
        s.brief_exists = True


def test_artifact_snapshot_extra_forbid() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ArtifactSnapshot(  # type: ignore[call-arg]
            brief_exists=False,
            senior_plan_exists=False,
            adr_status="none",
            junior_impl_commit_present=False,
            plan_vs_impl_verdict="absent",
            r0_a_verdict="absent",
            pr_merged=False,
            extra_field="bad",
        )


def test_gate_snapshot_frozen() -> None:
    from pydantic import ValidationError

    g = _gates()
    with pytest.raises(ValidationError):
        g.merge_clean = False


def test_gate_snapshot_extra_forbid() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GateSnapshot(merge_clean=True, unknown="bad")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# next_state — gated transitions (ADR-008 Decision 1)
# ---------------------------------------------------------------------------


def test_next_state_awaiting_brief_no_brief_returns_none() -> None:
    assert next_state(WorkflowState.AWAITING_BRIEF, _snap(), _gates()) is None


def test_next_state_awaiting_brief_brief_exists_advances() -> None:
    result = next_state(WorkflowState.AWAITING_BRIEF, _snap(brief_exists=True), _gates())
    assert result == WorkflowState.AWAITING_SENIOR_PLAN


def test_next_state_awaiting_senior_plan_no_plan_returns_none() -> None:
    assert next_state(WorkflowState.AWAITING_SENIOR_PLAN, _snap(), _gates()) is None


def test_next_state_awaiting_senior_plan_plan_exists_advances() -> None:
    result = next_state(
        WorkflowState.AWAITING_SENIOR_PLAN, _snap(senior_plan_exists=True), _gates()
    )
    assert result == WorkflowState.AWAITING_ARCHITECT_ACCEPT


# ---------------------------------------------------------------------------
# next_state — W-002-2b no-ADR routing (plan_has_adr discriminator)
# ---------------------------------------------------------------------------


def test_next_state_skips_accept_when_no_adr_key_in_frontmatter() -> None:
    """plan_has_adr=False (frontmatter present, no adr key) → skip accept gate."""
    result = next_state(
        WorkflowState.AWAITING_SENIOR_PLAN,
        _snap(senior_plan_exists=True, plan_has_adr=False),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_JUNIOR_IMPL


def test_next_state_routes_through_accept_when_adr_key_present() -> None:
    """plan_has_adr=True (frontmatter with adr key) → route through accept gate."""
    result = next_state(
        WorkflowState.AWAITING_SENIOR_PLAN,
        _snap(senior_plan_exists=True, plan_has_adr=True),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_ARCHITECT_ACCEPT


def test_next_state_legacy_no_frontmatter_routes_through_accept() -> None:
    """plan_has_adr=None (legacy: no frontmatter) → preserve today's behavior."""
    result = next_state(
        WorkflowState.AWAITING_SENIOR_PLAN,
        _snap(senior_plan_exists=True, plan_has_adr=None),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_ARCHITECT_ACCEPT


def test_next_state_awaiting_architect_accept_not_accepted_returns_none() -> None:
    result = next_state(
        WorkflowState.AWAITING_ARCHITECT_ACCEPT, _snap(adr_status="proposed"), _gates()
    )
    assert result is None


def test_next_state_awaiting_architect_accept_accepted_advances() -> None:
    result = next_state(
        WorkflowState.AWAITING_ARCHITECT_ACCEPT, _snap(adr_status="accepted"), _gates()
    )
    assert result == WorkflowState.AWAITING_JUNIOR_IMPL


def test_next_state_awaiting_junior_impl_no_commit_returns_none() -> None:
    assert next_state(WorkflowState.AWAITING_JUNIOR_IMPL, _snap(), _gates()) is None


def test_next_state_awaiting_junior_impl_commit_present_advances() -> None:
    result = next_state(
        WorkflowState.AWAITING_JUNIOR_IMPL,
        _snap(junior_impl_commit_present=True),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL


def test_next_state_awaiting_pr_merge_not_merged_returns_none() -> None:
    assert next_state(WorkflowState.AWAITING_PR_MERGE, _snap(), _gates()) is None


def test_next_state_awaiting_pr_merge_merged_closes() -> None:
    result = next_state(WorkflowState.AWAITING_PR_MERGE, _snap(pr_merged=True), _gates())
    assert result == WorkflowState.CLOSED


# ---------------------------------------------------------------------------
# AWAITING_SENIOR_PLAN_VS_IMPL → AWAITING_R0_A (ADR-008 Amendment 1, W-005)
# Route B: R0-A fires regardless of plan-vs-impl verdict.
# ---------------------------------------------------------------------------


def test_next_state_plan_vs_impl_absent_returns_none() -> None:
    """No plan-vs-impl artifact yet → no transition."""
    result = next_state(
        WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL,
        _snap(plan_vs_impl_verdict="absent"),
        _gates(),
    )
    assert result is None


def test_next_state_plan_vs_impl_clean_advances_to_r0_a() -> None:
    """Route B: clean plan-vs-impl → R0-A (unchanged from pre-amendment)."""
    result = next_state(
        WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL,
        _snap(plan_vs_impl_verdict="clean"),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_R0_A


def test_next_state_plan_vs_impl_blocking_route_b_still_advances_to_r0_a() -> None:
    """Route B (W-005): blocking plan-vs-impl no longer short-circuits to
    architect_decision; R0-A still fires."""
    result = next_state(
        WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL,
        _snap(plan_vs_impl_verdict="blocking"),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_R0_A


def test_next_state_plan_vs_impl_needs_architect_route_b_still_advances_to_r0_a() -> None:
    """Route B (W-005): needs_architect plan-vs-impl no longer short-circuits;
    R0-A still fires for cross-perspective audit."""
    result = next_state(
        WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL,
        _snap(plan_vs_impl_verdict="needs_architect"),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_R0_A


# ---------------------------------------------------------------------------
# AWAITING_R0_A → next (ADR-008 Amendment 1, W-005)
# Joint-verdict evaluation: both plan_vs_impl AND r0_a must be clean (+ merge)
# to advance to PR_MERGE; any non-clean from either review → architect_decision.
# ---------------------------------------------------------------------------


def test_next_state_r0_a_absent_returns_none() -> None:
    """R0-A not pushed yet → no transition."""
    result = next_state(
        WorkflowState.AWAITING_R0_A,
        _snap(plan_vs_impl_verdict="clean", r0_a_verdict="absent"),
        _gates(),
    )
    assert result is None


def test_next_state_r0_a_joint_clean_merge_clean_advances_to_pr_merge() -> None:
    """Joint verdict: both clean + merge_clean → PR_MERGE."""
    result = next_state(
        WorkflowState.AWAITING_R0_A,
        _snap(plan_vs_impl_verdict="clean", r0_a_verdict="clean"),
        _gates(merge_clean=True),
    )
    assert result == WorkflowState.AWAITING_PR_MERGE


def test_next_state_r0_a_joint_clean_merge_conflict_routes_to_architect_decision() -> None:
    """Joint verdict clean but merge conflict → architect_decision (Decision 8)."""
    result = next_state(
        WorkflowState.AWAITING_R0_A,
        _snap(plan_vs_impl_verdict="clean", r0_a_verdict="clean"),
        _gates(merge_clean=False),
    )
    assert result == WorkflowState.AWAITING_ARCHITECT_DECISION


def test_next_state_r0_a_plan_vs_impl_non_clean_routes_to_architect_decision() -> None:
    """Route B joint-verdict (W-005): R0-A clean but plan_vs_impl has findings →
    architect must still route plan_vs_impl findings."""
    result = next_state(
        WorkflowState.AWAITING_R0_A,
        _snap(plan_vs_impl_verdict="needs_architect", r0_a_verdict="clean"),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_ARCHITECT_DECISION


def test_next_state_r0_a_blocking_routes_to_architect_decision() -> None:
    """R0-A blocking → architect_decision regardless of plan_vs_impl."""
    result = next_state(
        WorkflowState.AWAITING_R0_A,
        _snap(plan_vs_impl_verdict="clean", r0_a_verdict="blocking"),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_ARCHITECT_DECISION


def test_next_state_r0_a_needs_architect_routes_to_architect_decision() -> None:
    """R0-A needs_architect → architect_decision regardless of plan_vs_impl."""
    result = next_state(
        WorkflowState.AWAITING_R0_A,
        _snap(plan_vs_impl_verdict="clean", r0_a_verdict="needs_architect"),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_ARCHITECT_DECISION


def test_next_state_r0_a_both_non_clean_routes_to_architect_decision() -> None:
    """Both verdicts non-clean → architect_decision (still one routing pass needed)."""
    result = next_state(
        WorkflowState.AWAITING_R0_A,
        _snap(plan_vs_impl_verdict="needs_architect", r0_a_verdict="blocking"),
        _gates(),
    )
    assert result == WorkflowState.AWAITING_ARCHITECT_DECISION


# ---------------------------------------------------------------------------
# record_override — ADR-008 Decision 10 + 11
# ---------------------------------------------------------------------------


def test_record_override_updates_state_and_appends_history() -> None:
    original = _state()
    override = OverrideEntry(
        timestamp=_NOW,
        actor="architect",
        from_state=WorkflowState.AWAITING_BRIEF,
        to_state=WorkflowState.AWAITING_SENIOR_PLAN,
        reason="brief was published out-of-band",
    )
    result = record_override(original, override)
    assert result.state == WorkflowState.AWAITING_SENIOR_PLAN
    assert len(result.override_history) == 1
    assert result.override_history[0].reason == "brief was published out-of-band"


def test_record_override_does_not_mutate_original() -> None:
    original = _state()
    override = OverrideEntry(
        timestamp=_NOW,
        actor="architect",
        from_state=WorkflowState.AWAITING_BRIEF,
        to_state=WorkflowState.AWAITING_SENIOR_PLAN,
        reason="test",
    )
    record_override(original, override)
    assert original.state == WorkflowState.AWAITING_BRIEF
    assert len(original.override_history) == 0


def test_record_override_rework_increments_cycle() -> None:
    original = _state(state=WorkflowState.AWAITING_ARCHITECT_DECISION, cycle=1)
    override = OverrideEntry(
        timestamp=_NOW,
        actor="architect",
        from_state=WorkflowState.AWAITING_ARCHITECT_DECISION,
        to_state=WorkflowState.AWAITING_JUNIOR_IMPL,
        reason="rework: R0-A finding resolved",
    )
    result = record_override(original, override)
    assert result.cycle == 2
    assert result.state == WorkflowState.AWAITING_JUNIOR_IMPL


def test_record_override_non_rework_does_not_change_cycle() -> None:
    original = _state(state=WorkflowState.AWAITING_R0_A, cycle=2)
    override = OverrideEntry(
        timestamp=_NOW,
        actor="architect",
        from_state=WorkflowState.AWAITING_R0_A,
        to_state=WorkflowState.AWAITING_PR_MERGE,
        reason="force-advance: R0-A author unavailable",
    )
    result = record_override(original, override)
    assert result.cycle == 2


def test_record_override_to_junior_impl_from_accept_does_not_increment_cycle() -> None:
    """P1.3-case regression: from=awaiting_architect_accept, to=awaiting_junior_impl
    must NOT increment cycle (rework requires from=awaiting_architect_decision).
    """
    original = _state(state=WorkflowState.AWAITING_ARCHITECT_ACCEPT, cycle=1)
    override = OverrideEntry(
        timestamp=_NOW,
        actor="architect",
        from_state=WorkflowState.AWAITING_ARCHITECT_ACCEPT,
        to_state=WorkflowState.AWAITING_JUNIOR_IMPL,
        reason="ADR accepted out-of-band; unblocking P1.3",
    )
    result = record_override(original, override)
    assert result.cycle == 1
    assert result.state == WorkflowState.AWAITING_JUNIOR_IMPL
    assert len(result.override_history) == 1
    assert result.last_transition_at == _NOW


def test_record_override_to_junior_impl_from_brief_does_not_increment_cycle() -> None:
    """Defense-in-depth: any from-state != AWAITING_ARCHITECT_DECISION is non-rework."""
    original = _state(state=WorkflowState.AWAITING_BRIEF, cycle=1)
    override = OverrideEntry(
        timestamp=_NOW,
        actor="architect",
        from_state=WorkflowState.AWAITING_BRIEF,
        to_state=WorkflowState.AWAITING_JUNIOR_IMPL,
        reason="emergency skip",
    )
    result = record_override(original, override)
    assert result.cycle == 1


def test_record_override_cycle_warning_fires_only_on_rework_reaching_threshold(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """cycle ≥ 4 warning emits only when from=AWAITING_ARCHITECT_DECISION."""
    # Rework path reaching cycle 4 → warning
    rework_state = _state(state=WorkflowState.AWAITING_ARCHITECT_DECISION, cycle=3)
    rework_override = OverrideEntry(
        timestamp=_NOW,
        actor="architect",
        from_state=WorkflowState.AWAITING_ARCHITECT_DECISION,
        to_state=WorkflowState.AWAITING_JUNIOR_IMPL,
        reason="rework: third attempt",
    )
    result = record_override(rework_state, rework_override)
    assert result.cycle == 4
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "cycle 4" in captured.err

    # Non-rework from accept → same initial cycle=3, to=JUNIOR_IMPL → no warning
    accept_state = _state(state=WorkflowState.AWAITING_ARCHITECT_ACCEPT, cycle=3)
    accept_override = OverrideEntry(
        timestamp=_NOW,
        actor="architect",
        from_state=WorkflowState.AWAITING_ARCHITECT_ACCEPT,
        to_state=WorkflowState.AWAITING_JUNIOR_IMPL,
        reason="unblock",
    )
    result2 = record_override(accept_state, accept_override)
    assert result2.cycle == 3
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# parse_verdict — §4 exception payload + §5 boundary validators
# ---------------------------------------------------------------------------


def test_parse_verdict_clean(tmp_path: Path) -> None:
    review = tmp_path / "R0-A.md"
    review.write_text("---\nverdict: clean\nfindings_count:\n  red: 0\n---\nbody\n")
    assert parse_verdict(review) == "clean"


def test_parse_verdict_blocking(tmp_path: Path) -> None:
    review = tmp_path / "R0-A.md"
    review.write_text("---\nverdict: blocking\n---\nbody\n")
    assert parse_verdict(review) == "blocking"


def test_parse_verdict_needs_architect(tmp_path: Path) -> None:
    review = tmp_path / "R0-A.md"
    review.write_text("---\nverdict: needs_architect\n---\nbody\n")
    assert parse_verdict(review) == "needs_architect"


def test_parse_verdict_missing_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "nonexistent.md"
    with pytest.raises(WorkflowError) as exc_info:
        parse_verdict(path)
    assert exc_info.value.path == path


def test_parse_verdict_missing_frontmatter_raises(tmp_path: Path) -> None:
    review = tmp_path / "R0-A.md"
    review.write_text("no frontmatter here\n")
    with pytest.raises(WorkflowError, match="missing YAML frontmatter"):
        parse_verdict(review)


def test_parse_verdict_missing_verdict_key_raises(tmp_path: Path) -> None:
    review = tmp_path / "R0-A.md"
    review.write_text("---\nfindings_count:\n  red: 0\n---\nbody\n")
    with pytest.raises(WorkflowError, match="missing required key 'verdict'") as exc_info:
        parse_verdict(review)
    assert exc_info.value.path == review


def test_parse_verdict_invalid_verdict_empty_raises(tmp_path: Path) -> None:
    review = tmp_path / "R0-A.md"
    review.write_text("---\nverdict: ''\n---\n")
    with pytest.raises(WorkflowError):
        parse_verdict(review)


def test_parse_verdict_invalid_verdict_typo_raises(tmp_path: Path) -> None:
    review = tmp_path / "R0-A.md"
    review.write_text("---\nverdict: almost_clean\n---\n")
    with pytest.raises(WorkflowError):
        parse_verdict(review)


# ---------------------------------------------------------------------------
# evaluate_merge_clean — §3 subprocess cleanup + timeout
# ---------------------------------------------------------------------------


def test_evaluate_merge_clean_returns_true_when_no_conflicts() -> None:
    mock_result = MagicMock()
    mock_result.stdout = "some diff output\nno conflict markers here\n"
    with patch("subprocess.run", return_value=mock_result):
        assert evaluate_merge_clean("feature-branch") is True


def test_evaluate_merge_clean_returns_false_when_conflicts() -> None:
    mock_result = MagicMock()
    mock_result.stdout = "<<<<<<< HEAD\nconflict\n=======\nother\n>>>>>>> branch\n"
    with patch("subprocess.run", return_value=mock_result):
        assert evaluate_merge_clean("feature-branch") is False


def test_evaluate_merge_clean_timeout_raises_workflow_error() -> None:
    with (
        patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30)),
        pytest.raises(WorkflowError, match="timed out"),
    ):
        evaluate_merge_clean("feature-branch")


def test_evaluate_merge_clean_os_error_raises_workflow_error() -> None:
    with (
        patch("subprocess.run", side_effect=OSError("git not found")),
        pytest.raises(WorkflowError),
    ):
        evaluate_merge_clean("feature-branch")
